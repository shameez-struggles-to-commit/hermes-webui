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
    out = _run_node(
        _extract(["_providerQuotaCardTargets"])
        + """
const out=_providerQuotaCardTargets({providers:[{id:'openai-codex',is_oauth:true,has_key:true}]},null);
console.log(JSON.stringify(out.map(t=>t.provider===null?'ACTIVE':t.provider)));
"""
    )
    assert out == ["ACTIVE", "openai-codex"]


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
const btn={addEventListener(){}};
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
