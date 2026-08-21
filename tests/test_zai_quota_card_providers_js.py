"""Behavioral tests for multi-provider quota cards on the Providers panel.

Executes the real panels.js functions under Node (extraction harness, same
pattern as test_zai_quota_chip_js.py). Covers: target selection (active +
configured OAuth providers), per-card fetch URLs, dataset wiring, and the
card builder's window rendering for a Codex-shaped status.

Run via ./scripts/test.sh per AGENTS.md.
"""

from __future__ import annotations

import re
import shutil
import subprocess

import pytest

PANELS_JS = "static/panels.js"


def _extract(names) -> str:
    source = open(PANELS_JS, encoding="utf-8").read()
    chunks = []
    for name in names:
        match = re.search(
            rf"(?<![A-Za-z0-9_])((?:async\s+)?function\s+{name}\s*\([^)]*\)\s*\{{)",
            source,
        )
        if not match:
            pytest.fail(f"{name} not found in {PANELS_JS}")
        start = match.start(1)
        depth = 0
        for i in range(start, len(source)):
            if source[i] == "{":
                depth += 1
            elif source[i] == "}":
                depth -= 1
                if depth == 0:
                    chunks.append(source[start:i + 1])
                    break
        else:
            pytest.fail(f"could not balance braces for {name}")
    return "\n".join(chunks)


def _run_node(script: str):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    result = subprocess.run(
        [node, "-e", script],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if result.returncode != 0:
        pytest.fail(f"node harness failed: {result.stderr[:1200]}")
    import json as _json
    return _json.loads(result.stdout)


def test_card_targets_active_plus_configured_oauth():
    out = _run_node(
        _extract(["_providerQuotaCardTargets"])
        + """
const data={providers:[{id:'openai-codex',is_oauth:true,has_key:true},{id:'zai',is_oauth:false,has_key:true},{id:'openai-codex',is_oauth:true,has_key:true},{id:'anthropic',is_oauth:true,has_key:true}]};
const out=_providerQuotaCardTargets(data,{provider:'zai'});
console.log(JSON.stringify(out.map(t=>t.provider===null?'ACTIVE':t.provider)));
"""
    )
    assert out == ["ACTIVE", "openai-codex", "anthropic"]


def test_card_targets_dedupes_active_slug():
    out = _run_node(
        _extract(["_providerQuotaCardTargets"])
        + """
const data={providers:[{id:'zai',is_oauth:true,has_key:true},{id:'openai-codex',is_oauth:true,has_key:true}]};
const out=_providerQuotaCardTargets(data,{provider:'zai'});
console.log(JSON.stringify(out.map(t=>t.provider===null?'ACTIVE':t.provider)));
"""
    )
    # active is zai: the OAuth zai entry must not duplicate it
    assert out == ["ACTIVE", "openai-codex"]


def test_card_targets_without_active_status():
    # Fail-closed: no active slug (active fetch failed) -> NO secondaries.
    out = _run_node(
        _extract(["_providerQuotaCardTargets"])
        + """
const out=_providerQuotaCardTargets({providers:[{id:'openai-codex',is_oauth:true,has_key:true}]},null);
console.log(JSON.stringify(out.map(t=>t.provider===null?'ACTIVE':t.provider)));
"""
    )
    assert out == ["ACTIVE"]


def test_fetch_url_includes_provider_param():
    out = _run_node(
        """
const calls=[];
global.api=async(url)=>{calls.push(url);return {ok:true,status:'available',provider:'x'};};
global.Date.now=()=>1234;
"""
        + _extract(["_fetchProviderQuotaStatus"])
        + """
(async()=>{
  await _fetchProviderQuotaStatus(false,'openai-codex');
  await _fetchProviderQuotaStatus(true,'openai-codex');
  await _fetchProviderQuotaStatus(false);
  console.log(JSON.stringify(calls));
})().catch(e=>{console.error(e);process.exit(1);});
"""
    )
    assert out == [
        "/api/provider/quota?provider=openai-codex",
        "/api/provider/quota?provider=openai-codex&refresh=1&ts=1234",
        "/api/provider/quota",
    ]


def test_build_card_sets_dataset_and_renders_windows():
    out = _run_node(
        """
const titleEl={textContent:''};
const btn={addEventListener(){},setAttribute(){},removeAttribute(){},disabled:false,textContent:''};
let _html='';
const stub={
  className:'', dataset:{},
  set innerHTML(v){_html=v;},
  get innerHTML(){return _html;},
  querySelector(sel){
    if(sel==='[data-provider-quota-refresh]') return btn;
    if(sel==='.provider-quota-title') return titleEl;
    return null;
  },
  addEventListener(){}
};
global.document={createElement(){return stub;}};
global.localStorage={getItem(){return null;},setItem(){}};
global.t=(k,...a)=>k;
global.esc=(s)=>String(s);
"""
        + _extract([
            "_formatProviderQuotaMoney",
            "_formatProviderQuotaPercent",
            "_formatProviderQuotaReset",
            "_formatProviderQuotaWindowLabel",
            "_formatProviderQuotaLastChecked",
            "_providerQuotaStateClass",
            "_providerQuotaStatusLabel",
            "_providerQuotaWindowMeta",
            "_providerQuotaRetryAfterText",
            "_providerQuotaUnavailableReason",
            "_providerQuotaPoolShouldDefaultOpen",
            "_buildProviderQuotaPoolBreakdown",
            "_buildProviderQuotaCard",
        ])
        + """
const status={ok:true,provider:'openai-codex',display_name:'OpenAI Codex',status:'available',
  account_limits:{provider:'openai-codex',plan:'Plus',available:true,
    windows:[{label:'Session',used_percent:18.0,remaining_percent:82.0,reset_at:'2026-08-27T02:11:37Z'},
             {label:'Weekly',used_percent:5.0,remaining_percent:95.0,reset_at:'2026-08-24T00:00:00Z'}],
    details:[],fetched_at:'2026-08-21T00:00:00Z'},
  message:'loaded'};
const card=_buildProviderQuotaCard(status);
console.log(JSON.stringify({dataset:card.dataset.providerQuota, html:_html.includes('provider_quota_session_limit')&&_html.includes('provider_quota_weekly_limit')&&_html.includes('82%')}));
"""
    )
    assert out["dataset"] == "openai-codex"
    assert out["html"] is True


def test_card_targets_require_configured_key():
    # has_key=false OAuth providers must NOT become fetch targets (doomed
    # fetch + potential Codex subprocess probe per panel load).
    out = _run_node(
        _extract(["_providerQuotaCardTargets"])
        + """
const data={providers:[{id:'openai-codex',is_oauth:true,has_key:false},{id:'nous',is_oauth:true,has_key:true}]};
const out=_providerQuotaCardTargets(data,{provider:'zai'});
console.log(JSON.stringify(out.map(t=>t.provider===null?'ACTIVE':t.provider)));
"""
    )
    assert out == ["ACTIVE", "nous"]


def test_should_render_card_allowlist():
    # Active: any truthy status renders (error states explain themselves).
    # Secondary: allowlist — ONLY ok+available renders (fail-closed against
    # future unexpected status values, GUIDELINES #3).
    out = _run_node(
        _extract(["_providerQuotaShouldRenderCard"])
        + """
const cases=[
  [{status:'available',ok:true},false,true],
  [{status:'unavailable'},false,false],
  [{status:'no_key'},false,false],
  [{status:'invalid_key'},false,false],
  [{status:'unsupported'},false,false],
  [{status:'some_future_status'},false,false],
  [{status:'unavailable'},true,true],
  [{status:'no_key'},true,true],
  [{},false,false],
  [null,false,false]
];
console.log(JSON.stringify(cases.map(c=>_providerQuotaShouldRenderCard(c[0],c[1]))));
"""
    )
    assert out == [True, False, False, False, False, False, True, True, False, False]


def test_targets_fail_closed_without_active_slug():
    # Active fetch failed (no provider echo): secondaries are skipped — the
    # active error card renders alone; no duplicate-card self-inconsistency.
    out = _run_node(
        _extract(["_providerQuotaCardTargets"])
        + """
const data={providers:[{id:'openai-codex',is_oauth:true,has_key:true},{id:'nous',is_oauth:true,has_key:true}]};
const out=_providerQuotaCardTargets(data,{ok:false,status:'unavailable',message:'x'});
console.log(JSON.stringify(out.map(t=>t.provider===null?'ACTIVE':t.provider)));
"""
    )
    assert out == ["ACTIVE"]


def test_failed_refresh_preserves_secondary_identity_and_subtitle():
    # The exact round-2 regression class: a FAILED refresh must keep the
    # card's provider slug (dataset), fetch URL, title, and subtitle.
    out = _run_node(
        """
const calls=[];
let failNext=true;
global.api=async(url)=>{
  calls.push(url);
  if(failNext) throw new Error('boom');
  return {ok:true,status:'available',provider:'openai-codex',display_name:'OpenAI Codex',account_limits:{provider:'openai-codex',plan:'Plus',available:true,windows:[{label:'Session',used_percent:10,remaining_percent:90,reset_at:'2026-08-27T00:00:00Z'}],details:[],fetched_at:'2026-08-21T00:00:00Z'}};
};
global.Date.now=()=>1234;
let _html='';
const titleEl={textContent:'Provider Quota'};
const subEl={textContent:'OpenAI Codex · Plus'};
const btn={addEventListener(){},setAttribute(){},removeAttribute(){},disabled:false,textContent:''};
const makeCard=()=>{const c={className:'',dataset:{providerQuota:'openai-codex',quotaCardSecondary:'1'},set innerHTML(v){_html=v;},get innerHTML(){return _html;},querySelector(sel){if(sel==='[data-provider-quota-refresh]')return btn;if(sel==='.provider-quota-title')return titleEl;if(sel==='.provider-quota-subtitle')return subEl;return null;},addEventListener(){}};return c;};
global.document={createElement(){return makeCard();}};
global.localStorage={getItem(){return null;},setItem(){}};
global.t=(k)=>k;
global.esc=(s)=>String(s);
global.showToast=()=>{};
"""
        + _extract([
            "_formatProviderQuotaMoney", "_formatProviderQuotaPercent", "_formatProviderQuotaReset",
            "_formatProviderQuotaWindowLabel", "_formatProviderQuotaLastChecked", "_providerQuotaStateClass",
            "_providerQuotaStatusLabel", "_providerQuotaWindowMeta", "_providerQuotaRetryAfterText",
            "_providerQuotaUnavailableReason", "_providerQuotaPoolShouldDefaultOpen",
            "_buildProviderQuotaPoolBreakdown", "_buildProviderQuotaCard",
            "_fetchProviderQuotaStatus", "_refreshProviderQuota",
        ])
        + """
(async()=>{
  const card=makeCard();
  await _refreshProviderQuota(card, btn);   // fails (throw)
  const afterFail={slug:card.dataset.providerQuota};
  failNext=false;
  await _refreshProviderQuota(card, btn);   // succeeds on retry
  console.log(JSON.stringify({
    afterFailSlug: afterFail.slug,
    secondFetchHadProvider: calls.length>1 && calls[1].includes('provider=openai-codex'),
    subtitlePreserved: subEl.textContent==='OpenAI Codex · Plus',
    title: titleEl.textContent
  }));
})().catch(e=>{console.error(e);process.exit(1);});
"""
    )
    assert out["afterFailSlug"] == "openai-codex"
    assert out["secondFetchHadProvider"] is True
    assert out["subtitlePreserved"] is True
    assert out["title"] == "provider_quota_title_other"
