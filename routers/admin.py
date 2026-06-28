import logging
from typing import Optional, Union

import markupsafe
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from auth import check_api_key
from config import Config
from services.channel_store import channel_store
from tg_client import tg_client_manager

logger = logging.getLogger("admin")
router = APIRouter(tags=["admin"])


class ChannelBody(BaseModel):
    id: Union[int, str]
    active: bool = True


class ActiveBody(BaseModel):
    active: bool


def _require_admin(request: Request, api_key: str = "") -> None:
    if not Config.API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Set API_KEY in environment to use the admin panel.",
        )
    check_api_key(api_key, request.query_params.get("api_key", ""))


@router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, api_key: str = ""):
    if not Config.API_KEY:
        return HTMLResponse(
            "<h1>Admin disabled</h1><p>Set API_KEY in your environment to enable channel management.</p>",
            status_code=503,
        )
    try:
        _require_admin(request, api_key)
    except HTTPException:
        key_input = markupsafe.escape(request.query_params.get("api_key", ""))
        return HTMLResponse(f"""
        <!DOCTYPE html><html><head><title>Admin Login</title>
        <style>body{{font-family:sans-serif;background:#09090b;color:#f4f4f5;display:flex;align-items:center;justify-content:center;min-height:100vh}}
        .card{{background:#18181b;border:1px solid #27272a;padding:32px;border-radius:12px;width:360px}}
        input{{width:100%;padding:10px;margin:12px 0;background:#09090b;border:1px solid #27272a;color:#fff;border-radius:6px}}
        button{{width:100%;padding:10px;background:#2563eb;color:#fff;border:none;border-radius:6px;cursor:pointer}}</style></head>
        <body><div class="card"><h2>Channel Admin</h2>
        <form method="get"><input name="api_key" type="password" placeholder="API Key" value="{key_input}" required>
        <button type="submit">Open Admin</button></form></div></body></html>
        """)

    escaped_key = markupsafe.escape(api_key or request.query_params.get("api_key", ""))
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Channel Admin</title>
<style>
:root{{--bg:#09090b;--card:#18181b;--border:#27272a;--text:#f4f4f5;--muted:#a1a1aa;--primary:#2563eb;--danger:#ef4444;--ok:#22c55e}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:Inter,system-ui,sans-serif;background:var(--bg);color:var(--text);padding:24px;max-width:900px;margin:0 auto}}
h1{{font-size:1.5rem;margin-bottom:8px}} p{{color:var(--muted);margin-bottom:20px;font-size:.9rem}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:20px;margin-bottom:16px}}
.row{{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px}}
input,select{{flex:1;min-width:180px;padding:10px;background:#09090b;border:1px solid var(--border);color:var(--text);border-radius:6px}}
button,.btn{{padding:10px 16px;border:none;border-radius:6px;cursor:pointer;font-size:.85rem}}
.btn-primary{{background:var(--primary);color:#fff}} .btn-danger{{background:var(--danger);color:#fff}}
.btn-muted{{background:#27272a;color:var(--text)}}
table{{width:100%;border-collapse:collapse;font-size:.88rem}}
th,td{{padding:10px 8px;border-bottom:1px solid var(--border);text-align:left}}
.badge{{padding:2px 8px;border-radius:999px;font-size:.75rem}}
.badge-on{{background:#14532d;color:#bbf7d0}} .badge-off{{background:#3f3f46;color:#d4d4d8}}
#msg{{margin-bottom:12px;font-size:.85rem;color:var(--ok);min-height:1.2em}}
a{{color:#60a5fa}}
</style></head><body>
<h1>Channel Manager</h1>
<p>Add, remove, or enable/disable Telegram channels without editing HF secrets. Changes persist in <code>data/channels.json</code>.</p>
<div id="msg"></div>
<div class="card">
  <h3 style="margin-bottom:12px">Add channel</h3>
  <div class="row">
    <input id="addInput" placeholder="Channel ID (-100...) or @username">
    <button class="btn-primary" onclick="addChannel()">Add</button>
    <button class="btn-muted" onclick="discoverChannels()">Discover from Telegram</button>
  </div>
  <div id="discover" style="margin-top:10px;font-size:.85rem;color:var(--muted)"></div>
</div>
<div class="card">
  <h3 style="margin-bottom:12px">Configured channels</h3>
  <table><thead><tr><th>Title</th><th>ID</th><th>Status</th><th>Actions</th></tr></thead>
  <tbody id="channelTable"><tr><td colspan="4">Loading...</td></tr></tbody></table>
</div>
<p><a href="/?api_key={escaped_key}">← Back to addon home</a></p>
<script>
const API_KEY = "{escaped_key}";
const headers = {{"Content-Type":"application/json"}};
function qs() {{ return "?api_key=" + encodeURIComponent(API_KEY); }}
function showMsg(t, ok=true) {{ document.getElementById("msg").style.color = ok ? "#22c55e" : "#ef4444"; document.getElementById("msg").textContent = t; }}
async function loadChannels() {{
  const res = await fetch("/admin/api/channels" + qs());
  const data = await res.json();
  const tbody = document.getElementById("channelTable");
  if (!data.channels || !data.channels.length) {{
    tbody.innerHTML = '<tr><td colspan="4">No channels yet. Add one above.</td></tr>';
    return;
  }}
  tbody.innerHTML = data.channels.map(ch => {{
    const st = ch.active ? '<span class="badge badge-on">ON</span>' : '<span class="badge badge-off">OFF</span>';
    const toggle = ch.active ? 'Disable' : 'Enable';
    const id = String(ch.id);
    return `<tr>
      <td>${{ch.title || id}}</td><td><code>${{id}}</code></td><td>${{st}}</td>
      <td>
        <button class="btn-muted" onclick="toggleChannel('${{id}}', ${{!ch.active}})">${{toggle}}</button>
        <button class="btn-danger" onclick="removeChannel('${{id}}')">Remove</button>
      </td></tr>`;
  }}).join("");
}}
async function addChannel() {{
  const val = document.getElementById("addInput").value.trim();
  if (!val) return;
  const res = await fetch("/admin/api/channels" + qs(), {{
    method:"POST", headers, body: JSON.stringify({{id: val, active: true}})
  }});
  const data = await res.json();
  if (!res.ok) {{ showMsg(data.detail || "Failed", false); return; }}
  showMsg("Channel added.");
  document.getElementById("addInput").value = "";
  loadChannels();
}}
async function removeChannel(id) {{
  if (!confirm("Remove channel " + id + "?")) return;
  const res = await fetch("/admin/api/channels/" + encodeURIComponent(id) + qs(), {{method:"DELETE"}});
  if (!res.ok) {{ showMsg("Remove failed", false); return; }}
  showMsg("Channel removed.");
  loadChannels();
}}
async function toggleChannel(id, active) {{
  const res = await fetch("/admin/api/channels/" + encodeURIComponent(id) + qs(), {{
    method:"PATCH", headers, body: JSON.stringify({{active}})
  }});
  if (!res.ok) {{ showMsg("Update failed", false); return; }}
  showMsg(active ? "Channel enabled." : "Channel disabled.");
  loadChannels();
}}
async function discoverChannels() {{
  const el = document.getElementById("discover");
  el.textContent = "Searching your Telegram dialogs...";
  const res = await fetch("/admin/api/discover" + qs());
  const data = await res.json();
  if (!res.ok) {{ el.textContent = data.detail || "Discovery failed"; return; }}
  if (!data.channels.length) {{ el.textContent = "No new channels found."; return; }}
  el.innerHTML = data.channels.map(ch =>
    `<div style="margin:6px 0">${{ch.title}} (<code>${{ch.id}}</code>)
     <button class="btn-muted" onclick="quickAdd('${{ch.id}}')">Add</button></div>`
  ).join("");
}}
async function quickAdd(id) {{
  document.getElementById("addInput").value = id;
  await addChannel();
  discoverChannels();
}}
loadChannels();
</script></body></html>"""
    return HTMLResponse(html)


@router.get("/admin/api/channels")
async def api_list_channels(request: Request, api_key: str = ""):
    _require_admin(request, api_key)
    channels = await tg_client_manager.get_channels_info()
    return {"channels": channels}


@router.post("/admin/api/channels")
async def api_add_channel(body: ChannelBody, request: Request, api_key: str = ""):
    _require_admin(request, api_key)
    try:
        chat = await tg_client_manager.client.get_chat(body.id)
        entry = channel_store.add_channel(
            chat.id,
            title=chat.title or str(chat.id),
            username=chat.username or "",
            active=body.active,
        )
        await tg_client_manager._resolve_channel(chat.id)
        return {"channel": entry}
    except Exception as e:
        logger.error(f"Admin add channel failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/admin/api/channels/{channel_id}")
async def api_remove_channel(channel_id: str, request: Request, api_key: str = ""):
    _require_admin(request, api_key)
    ref: Union[int, str] = int(channel_id) if channel_id.lstrip("-").isdigit() else channel_id
    if not channel_store.remove_channel(ref):
        raise HTTPException(status_code=404, detail="Channel not found")
    return {"ok": True}


@router.patch("/admin/api/channels/{channel_id}")
async def api_update_channel(channel_id: str, body: ActiveBody, request: Request, api_key: str = ""):
    _require_admin(request, api_key)
    ref: Union[int, str] = int(channel_id) if channel_id.lstrip("-").isdigit() else channel_id
    if not channel_store.set_active(ref, body.active):
        raise HTTPException(status_code=404, detail="Channel not found")
    return {"ok": True}


@router.get("/admin/api/discover")
async def api_discover_channels(request: Request, api_key: str = ""):
    _require_admin(request, api_key)
    if not Config.USER_SESSION_STRING:
        raise HTTPException(
            status_code=400,
            detail="Channel discovery requires USER_SESSION_STRING.",
        )
    from services.channels import channel_key

    known = {channel_key(ch["id"]) for ch in channel_store.list_channels()}
    found = []
    async for dialog in tg_client_manager.client.get_dialogs(limit=200):
        if not dialog.chat or dialog.chat.type not in ("channel", "supergroup"):
            continue
        if channel_key(dialog.chat.id) in known:
            continue
        found.append({
            "id": dialog.chat.id,
            "title": dialog.chat.title or str(dialog.chat.id),
            "username": dialog.chat.username or "",
        })
        if len(found) >= 30:
            break
    return {"channels": found}
