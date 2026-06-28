import os
import urllib.parse
import markupsafe
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, FileResponse, Response
from config import Config
from services.channels import channel_key
from tg_client import tg_client_manager

router = APIRouter(tags=["pages"])

@router.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def landing(request: Request):
    api_key = request.query_params.get("api_key", "")
    if api_key:
        manifest_url = f"{Config.ADDON_URL}/{urllib.parse.quote(api_key)}/manifest.json"
    else:
        manifest_url = f"{Config.ADDON_URL}/manifest.json"
        
    escaped_manifest_url = markupsafe.escape(manifest_url)
    escaped_stremio_url = markupsafe.escape(manifest_url.replace('http://', '').replace('https://', ''))
    
    web_stremio_url = f"https://web.stremio.com/#/addons?addon={urllib.parse.quote(manifest_url)}"
    escaped_web_stremio_url = markupsafe.escape(web_stremio_url)
    
    api_key_section = ""
    if Config.API_KEY:
        escaped_api_key = markupsafe.escape(api_key)
        api_key_section = f"""
                <div class="url-section" style="margin-bottom: 16px;">
                    <div class="section-title">Enter API Key</div>
                    <div class="input-group">
                        <input class="url-box" id="apiKeyInput" type="text" placeholder="Enter your API Key..." value="{escaped_api_key}" oninput="updateManifestUrl()">
                    </div>
                </div>
        """

    admin_link = ""
    if Config.API_KEY:
        admin_url = f"{Config.ADDON_URL}/admin?api_key={urllib.parse.quote(api_key or '')}"
        admin_link = f' | <a href="{markupsafe.escape(admin_url)}">Manage Channels</a>'

    channel_section = ""
    configured = Config.get_channel_ids()
    if len(configured) > 1:
        active_keys = {channel_key(c) for c in Config.get_active_channel_ids()}
        url_channels = request.query_params.get("channels", "").strip()
        url_selected = (
            {channel_key(c) for c in Config._parse_channel_ids(url_channels)}
            if url_channels
            else None
        )
        try:
            channel_infos = await tg_client_manager.get_channels_info()
        except Exception:
            channel_infos = [
                {"id": c, "title": str(c), "username": ""} for c in configured
            ]
        checkboxes = []
        for ch in channel_infos:
            cid = ch["id"]
            cid_str = str(cid)
            title = markupsafe.escape(ch.get("title", cid_str))
            if url_selected is not None:
                is_checked = channel_key(cid) in url_selected
            else:
                is_checked = channel_key(cid) in active_keys
            checked_attr = "checked" if is_checked else ""
            checkboxes.append(
                f'<label class="channel-option">'
                f'<input type="checkbox" name="channelSelect" value="{markupsafe.escape(cid_str)}" '
                f'{checked_attr} onchange="updateManifestUrl()">'
                f"<span>{title}</span></label>"
            )
        channel_section = f"""
                <div class="url-section" style="margin-bottom: 16px;">
                    <div class="section-title">Select Channels</div>
                    <p style="font-size: 0.8rem; color: var(--text-secondary); margin-bottom: 12px;">
                        Only checked channels are searched and streamed.
                    </p>
                    <div class="channel-list">{"".join(checkboxes)}</div>
                </div>
        """
        
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Telegram Addon by SunilRoy-dev</title>
            <meta name="description" content="Stream private Telegram files directly inside Stremio. Secure, lightweight, and ranges-supported proxy.">
            <link rel="preconnect" href="https://fonts.googleapis.com">
            <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
            <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
            <style>
                :root {{
                    --bg-dark: #09090b;
                    --bg-card: #18181b;
                    --border-muted: #27272a;
                    --text-primary: #f4f4f5;
                    --text-secondary: #a1a1aa;
                    --text-muted: #71717a;
                    --color-primary: #2563eb;
                    --color-primary-hover: #1d4ed8;
                    --color-accent: #60a5fa;
                    --font-title: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                    --font-body: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                }}
                * {{
                    box-sizing: border-box;
                    margin: 0;
                    padding: 0;
                }}
                body {{
                    font-family: var(--font-body);
                    background-color: var(--bg-dark);
                    color: var(--text-primary);
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    min-height: 100vh;
                    padding: 40px 20px;
                    margin: 0;
                    overflow-x: hidden;
                }}
                .app-card {{
                    background-color: var(--bg-card);
                    border: 1px solid var(--border-muted);
                    border-radius: 12px;
                    padding: 40px;
                    width: 100%;
                    max-width: 680px;
                    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
                    position: relative;
                }}
                .nav-header {{
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    margin-bottom: 32px;
                }}
                .brand {{
                    display: flex;
                    align-items: center;
                    gap: 10px;
                    font-family: var(--font-title);
                    font-weight: 700;
                    font-size: 1.1rem;
                    letter-spacing: -0.02em;
                    color: var(--text-primary);
                }}
                .brand-logo {{
                    width: 28px;
                    height: 28px;
                }}
                .star-badge {{
                    display: inline-flex;
                    align-items: center;
                    gap: 6px;
                    background: linear-gradient(135deg, #fbbf24 0%, #d97706 100%);
                    color: #09090b;
                    padding: 8px 14px;
                    border-radius: 6px;
                    font-size: 0.78rem;
                    font-weight: 700;
                    text-decoration: none;
                    box-shadow: 0 0 15px rgba(251, 191, 36, 0.3);
                    transition: all 0.3s ease;
                }}
                .star-badge:hover {{
                    transform: translateY(-2px);
                    box-shadow: 0 0 20px rgba(251, 191, 36, 0.6);
                    color: #000000;
                }}
                .hero {{
                    text-align: center;
                    margin-bottom: 32px;
                }}
                .hero h1 {{
                    font-family: var(--font-title);
                    font-size: 2rem;
                    font-weight: 700;
                    line-height: 1.25;
                    letter-spacing: -0.02em;
                    margin: 8px 0 16px 0;
                    color: #ffffff;
                }}
                .hero p {{
                    font-size: 0.95rem;
                    color: var(--text-secondary);
                    line-height: 1.5;
                    max-width: 520px;
                    margin: 0 auto;
                }}
                .url-section {{
                    background: #09090b;
                    border: 1px solid var(--border-muted);
                    border-radius: 8px;
                    padding: 20px;
                    margin-bottom: 24px;
                }}
                .channel-list {{
                    display: flex;
                    flex-direction: column;
                    gap: 10px;
                }}
                .channel-option {{
                    display: flex;
                    align-items: center;
                    gap: 10px;
                    font-size: 0.85rem;
                    color: var(--text-primary);
                    cursor: pointer;
                }}
                .channel-option input {{
                    accent-color: var(--color-primary);
                }}
                .section-title {{
                    font-family: var(--font-title);
                    font-size: 0.8rem;
                    font-weight: 700;
                    text-transform: uppercase;
                    letter-spacing: 0.05em;
                    color: var(--text-secondary);
                    margin-bottom: 12px;
                }}
                .input-group {{
                    display: flex;
                    gap: 10px;
                }}
                .url-box {{
                    flex: 1;
                    background-color: #18181b;
                    border: 1px solid #27272a;
                    color: var(--text-primary);
                    padding: 12px 16px;
                    border-radius: 6px;
                    font-size: 0.85rem;
                    font-family: monospace;
                    outline: none;
                    transition: border-color 0.2s;
                }}
                .url-box:focus {{
                    border-color: var(--color-primary);
                }}
                .btn-copy {{
                    background: #27272a;
                    border: 1px solid #3f3f46;
                    color: var(--text-primary);
                    padding: 0 16px;
                    border-radius: 6px;
                    font-size: 0.85rem;
                    font-weight: 500;
                    cursor: pointer;
                    display: inline-flex;
                    align-items: center;
                    gap: 6px;
                    transition: all 0.2s;
                }}
                .btn-copy:hover {{
                    background: #3f3f46;
                    border-color: #52525b;
                }}
                .button-group {{
                    display: grid;
                    grid-template-columns: 1fr;
                    gap: 12px;
                    margin-bottom: 32px;
                }}
                @media (min-width: 520px) {{
                    .button-group {{
                        grid-template-columns: 1fr 1fr;
                    }}
                }}
                .btn {{
                    padding: 12px 20px;
                    font-family: var(--font-body);
                    font-size: 0.9rem;
                    font-weight: 500;
                    text-decoration: none;
                    border-radius: 6px;
                    text-align: center;
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    gap: 8px;
                    transition: all 0.2s;
                }}
                .btn-primary {{
                    background-color: var(--color-primary);
                    color: #ffffff;
                }}
                .btn-primary:hover {{
                    background-color: var(--color-primary-hover);
                }}
                .btn-secondary {{
                    background: #27272a;
                    border: 1px solid #3f3f46;
                    color: var(--text-primary);
                }}
                .btn-secondary:hover {{
                    background: #3f3f46;
                    border-color: #52525b;
                }}
                .troubleshoot-details {{
                    background: #09090b;
                    border: 1px solid var(--border-muted);
                    border-radius: 8px;
                    padding: 16px;
                    margin-bottom: 24px;
                }}
                .troubleshoot-summary {{
                    font-family: var(--font-title);
                    font-size: 0.9rem;
                    font-weight: 600;
                    color: var(--text-primary);
                    cursor: pointer;
                    display: flex;
                    align-items: center;
                    user-select: none;
                    outline: none;
                }}
                .troubleshoot-content {{
                    margin-top: 14px;
                    font-size: 0.85rem;
                    color: var(--text-secondary);
                    line-height: 1.5;
                    border-top: 1px solid #27272a;
                    padding-top: 14px;
                }}
                .troubleshoot-content ol {{
                    margin-left: 20px;
                    margin-top: 8px;
                }}
                .troubleshoot-content li {{
                    margin-bottom: 6px;
                }}
                .features-grid {{
                    display: grid;
                    grid-template-columns: 1fr;
                    gap: 16px;
                    margin-bottom: 32px;
                }}
                @media (min-width: 600px) {{
                    .features-grid {{
                        grid-template-columns: 1fr 1fr;
                    }}
                }}
                .feature-card {{
                    background: #18181b;
                    border: 1px solid var(--border-muted);
                    border-radius: 8px;
                    padding: 20px;
                }}
                .feature-icon {{
                    width: 36px;
                    height: 36px;
                    background: #27272a;
                    border-radius: 6px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    color: var(--color-accent);
                    margin-bottom: 12px;
                }}
                .feature-title {{
                    font-family: var(--font-title);
                    font-size: 0.95rem;
                    font-weight: 600;
                    margin-bottom: 6px;
                    color: var(--text-primary);
                }}
                .feature-desc {{
                    font-size: 0.8rem;
                    color: var(--text-secondary);
                    line-height: 1.45;
                }}
                .license-card {{
                    background: #18181b;
                    border: 1px solid var(--border-muted);
                    border-radius: 8px;
                    padding: 20px;
                    margin-bottom: 32px;
                }}
                .license-title {{
                    font-family: var(--font-title);
                    font-size: 0.9rem;
                    font-weight: 600;
                    color: var(--text-primary);
                    margin-bottom: 6px;
                }}
                .license-text {{
                    font-size: 0.8rem;
                    color: var(--text-secondary);
                    line-height: 1.45;
                }}
                .footer {{
                    text-align: center;
                    font-size: 0.78rem;
                    color: var(--text-muted);
                    border-top: 1px solid var(--border-muted);
                    padding-top: 24px;
                    line-height: 1.6;
                }}
                .footer a {{
                    color: var(--text-secondary);
                    text-decoration: none;
                    font-weight: 500;
                    transition: color 0.2s;
                }}
                .footer a:hover {{
                    color: var(--text-primary);
                    text-decoration: underline;
                }}
                .footer em {{
                    display: block;
                    margin-top: 6px;
                    color: var(--text-muted);
                    font-style: normal;
                }}
            </style>
        </head>
        <body>
            <div class="app-card">
                <div class="nav-header">
                    <div class="brand">
                        <svg class="brand-logo" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <path d="M12 22C17.5228 22 22 17.5228 22 12C22 6.47715 17.5228 2 12 2C6.47715 2 2 6.47715 2 12C2 17.5228 6.47715 22 12 22Z" fill="url(#logoGrad)"/>
                            <path fill-rule="evenodd" clip-rule="evenodd" d="M16.974 8.23272C17.1568 7.2796 16.2004 6.5492 15.3533 6.94008L6.46743 11.0398C5.72727 11.3813 5.76103 12.4431 6.51651 12.7336L8.85507 13.6331C9.52554 13.891 10.2831 13.7828 10.8553 13.3486L14.4754 10.6011C14.6195 10.4917 14.7766 10.7042 14.6534 10.8406L11.597 14.2238C11.107 14.7663 11.2335 15.6322 11.854 16.015L15.3854 18.1936C16.1471 18.6635 17.1264 18.0673 17.0792 17.1685L16.974 8.23272Z" fill="white"/>
                            <defs>
                                <linearGradient id="logoGrad" x1="2" y1="2" x2="22" y2="22" gradientUnits="userSpaceOnUse">
                                    <stop stop-color="#3b82f6"/>
                                    <stop offset="1" stop-color="#1d4ed8"/>
                                </linearGradient>
                            </defs>
                        </svg>
                        Stremio Telegram Addon
                    </div>
                    <div class="header-actions">
                        <a href="https://github.com/SunilRoy-dev/stremio-telegram-debrid" target="_blank" class="star-badge">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" stroke="none" style="margin-right: 4px;"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg>
                            Star on GitHub
                        </a>
                    </div>
                </div>
                
                <div class="hero">
                    <h1>Stremio Telegram Addon</h1>
                    <p>A self-hosted Stremio addon proxy to stream videos, audios, and segmented archive parts directly from Telegram.</p>
                </div>
                
                {api_key_section}
                {channel_section}
                <div class="url-section">
                    <div class="section-title">Addon Manifest URL</div>
                    <div class="input-group">
                        <input class="url-box" id="manifestUrl" type="text" readonly value="{escaped_manifest_url}">
                        <button class="btn-copy" id="btnCopy" onclick="copyManifestUrl()">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="feather feather-copy"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
                            <span id="btnCopyText">Copy</span>
                        </button>
                    </div>
                </div>
                
                <div class="button-group">
                    <a class="btn btn-primary" id="installApp" href="stremio://{escaped_stremio_url}">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
                        Install on Stremio App
                    </a>
                    <a class="btn btn-secondary" id="installWeb" href="{escaped_web_stremio_url}" target="_blank">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
                        Install on Stremio Web
                    </a>
                </div>
                
                <details class="troubleshoot-details">
                    <summary class="troubleshoot-summary">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 8px; color: #fbbf24;"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>
                        Local Deployment Troubleshooting
                    </summary>
                    <div class="troubleshoot-content">
                        This error <strong>only occurs in local HTTP deployments</strong>. If you deploy this project to a secure public HTTPS server (such as Hugging Face Spaces, Render, or Koyeb), this installation button will work <strong>flawlessly</strong>.
                        <br><br>
                        For local deployments, Stremio's desktop protocol handler (<strong>stremio://</strong>) strips local ports and forces HTTPS, resulting in connection failure.
                        <br><br>
                        <strong>How to install locally:</strong>
                        <ol>
                            <li>Click the <strong>Copy</strong> button on the manifest URL field above.</li>
                            <li>Open the <strong>Stremio Desktop App</strong>.</li>
                            <li>Navigate to <strong>Add-ons</strong> (puzzle icon in the sidebar).</li>
                            <li>Paste the copied URL directly into the <strong>Add-on Repository URL</strong> input box at the bottom and click <strong>Install</strong>.</li>
                            <li>Alternatively, use the <strong>Install on Stremio Web</strong> button above.</li>
                        </ol>
                    </div>
                </details>
                
                <div class="features-grid">
                    <div class="feature-card">
                        <div class="feature-icon">
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path></svg>
                        </div>
                        <div class="feature-title">Segmented File Stitching</div>
                        <div class="feature-desc">Groups and stitches split file parts (.001, .part1, etc.) into a virtual continuous stream on the fly.</div>
                    </div>
                    <div class="feature-card">
                        <div class="feature-icon">
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="12 2 2 7 12 12 22 7 12 2"></polygon><polyline points="2 17 12 22 22 17"></polyline><polyline points="2 12 12 17 22 12"></polyline></svg>
                        </div>
                        <div class="feature-title">Range-Seek Support</div>
                        <div class="feature-desc">Full byte-range support allows you to skip forward or seek backward instantly inside your media player.</div>
                    </div>
                    <div class="feature-card">
                        <div class="feature-icon">
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>
                        </div>
                        <div class="feature-title">Subtitle Mapping</div>
                        <div class="feature-desc">Scans the channel dynamically for matching subtitle files (.srt, .vtt, .ass) and injects them.</div>
                    </div>
                    <div class="feature-card">
                        <div class="feature-icon">
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path></svg>
                        </div>
                        <div class="feature-title">Access Control</div>
                        <div class="feature-desc">Protects endpoints with a secure API key check to prevent unauthorized use of your proxy.</div>
                    </div>
                </div>
                
                <div class="license-card">
                    <div class="license-title">License: MIT Non-Commercial License (MIT-NC)</div>
                    <div class="license-text">
                        This software is published under a custom <strong>MIT Non-Commercial License (MIT-NC)</strong>. Sublicensing, commercial distribution, renting, or monetization of this code or its derivatives is strictly prohibited. Attribution must be preserved in all copies.
                    </div>
                </div>
                
                <div class="footer">
                    Developed by <a href="https://github.com/SunilRoy-dev" target="_blank">SunilRoy-dev</a> | Licensed under MIT-NC{admin_link}
                    <em>For educational and personal testing only. Do not use for unauthorized hosting or distribution of copyrighted media.</em>
                </div>
            </div>
            
            <script>
                const baseManifestUrl = "{Config.ADDON_URL}/manifest.json";
                const baseStremioUrl = baseManifestUrl.replace('http://', '').replace('https://', '');
                
                function getSelectedChannels() {{
                    const boxes = document.querySelectorAll('input[name="channelSelect"]:checked');
                    return Array.from(boxes).map(function(b) {{ return b.value; }}).join(',');
                }}

                function updateManifestUrl() {{
                    const apiKeyInput = document.getElementById("apiKeyInput");
                    const manifestUrlEl = document.getElementById("manifestUrl");
                    const installAppEl = document.getElementById("installApp");
                    const installWebEl = document.getElementById("installWeb");
                    
                    let apiKey = "";
                    if (apiKeyInput) {{
                        apiKey = apiKeyInput.value.trim();
                    }} else {{
                        apiKey = new URLSearchParams(window.location.search).get("api_key") || "";
                    }}
                    
                    let manifestUrl = baseManifestUrl;
                    let stremioUrl = baseStremioUrl;
                    
                    if (apiKey) {{
                        const encodedKey = encodeURIComponent(apiKey);
                        manifestUrl = "{Config.ADDON_URL}/" + encodedKey + "/manifest.json";
                        stremioUrl = baseStremioUrl.replace("manifest.json", encodedKey + "/manifest.json");
                    }}

                    const channels = getSelectedChannels();
                    const totalChannels = document.querySelectorAll('input[name="channelSelect"]').length;
                    const queryParts = [];
                    if (channels && totalChannels > 0) {{
                        queryParts.push("channels=" + encodeURIComponent(channels));
                    }}
                    if (queryParts.length) {{
                        manifestUrl += "?" + queryParts.join("&");
                        stremioUrl += "?" + queryParts.join("&");
                    }}
                    
                    if (manifestUrlEl) {{
                        manifestUrlEl.value = manifestUrl;
                    }}
                    if (installAppEl) {{
                        installAppEl.href = "stremio://" + stremioUrl;
                    }}
                    if (installWebEl) {{
                        installWebEl.href = "https://web.stremio.com/#/addons?addon=" + encodeURIComponent(manifestUrl);
                    }}
                }}

                function copyManifestUrl() {{
                    var copyText = document.getElementById("manifestUrl");
                    copyText.select();
                    copyText.setSelectionRange(0, 99999);
                    navigator.clipboard.writeText(copyText.value);
                    
                    var btnText = document.getElementById("btnCopyText");
                    var originalText = btnText.innerHTML;
                    btnText.innerHTML = "Copied!";
                    
                    var copyBtn = document.getElementById("btnCopy");
                    
                    copyBtn.style.background = "#22c55e";
                    copyBtn.style.borderColor = "#22c55e";
                    copyBtn.style.color = "#ffffff";
                    
                    setTimeout(function() {{
                        btnText.innerHTML = originalText;
                        copyBtn.style.background = "";
                        copyBtn.style.borderColor = "";
                        copyBtn.style.color = "";
                    }}, 2000);
                }}

                window.onload = function() {{
                    updateManifestUrl();
                }};
            </script>
        </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@router.get("/stremio_telegram_logo.png")
async def get_logo():
    if os.path.exists("stremio_telegram_logo.png"):
        return FileResponse("stremio_telegram_logo.png")
    return Response(status_code=404)

@router.get("/stremio_telegram_banner.png")
async def get_banner():
    if os.path.exists("stremio_telegram_banner.png"):
        return FileResponse("stremio_telegram_banner.png")
    return Response(status_code=404)
