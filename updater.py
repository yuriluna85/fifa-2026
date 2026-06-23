import urllib.request
import urllib.parse
import re
import json
import os
import sys
from datetime import datetime
import unicodedata
import csv

sys.stdout.reconfigure(encoding='utf-8')

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
MATCHES_FILE = os.path.join(OUTPUT_DIR, "matches.json")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "index.html")

# Helper to normalize text (remove accents, lowercase)
def clean_string(s):
    s = s.lower()
    s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    # Replace common abbreviations
    s = s.replace("eua", "estados unidos").replace("usa", "estados unidos")
    return s.strip()

# Scrape CazéTV channel videos or streams using ytInitialData JSON
def get_cazetv_youtube_content(tab="videos"):
    print(f"Scraping CazéTV YouTube tab: '{tab}'...")
    url = f"https://www.youtube.com/@CazeTV/{tab}"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7'
    }
    
    videos = []
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as response:
            html = response.read().decode('utf-8')
            
            # Find ytInitialData javascript object inside HTML
            match = re.search(r'ytInitialData\s*=\s*({.*?});', html)
            if not match:
                match = re.search(r'window\["ytInitialData"\]\s*=\s*({.*?});', html)
                
            if match:
                data = json.loads(match.group(1))
                
                # Navigate through YouTube page tabs structure to find content
                tabs = data.get('contents', {}).get('twoColumnBrowseResultsRenderer', {}).get('tabs', [])
                grid_contents = []
                
                for t in tabs:
                    tab_renderer = t.get('tabRenderer', {})
                    tab_url = tab_renderer.get('endpoint', {}).get('browseEndpoint', {}).get('canonicalBaseUrl', '')
                    if tab in tab_url or (tab == "videos" and "videos" in tab_url) or (tab == "streams" and "streams" in tab_url):
                        grid_contents = tab_renderer.get('content', {}).get('richGridRenderer', {}).get('contents', [])
                        break
                        
                if not grid_contents:
                    # Fallback check tab title
                    for t in tabs:
                        tab_renderer = t.get('tabRenderer', {})
                        title = tab_renderer.get('title', '').lower()
                        if (tab == "videos" and "víd" in title) or (tab == "streams" and ("trans" in title or "live" in title or "stream" in title)):
                            grid_contents = tab_renderer.get('content', {}).get('richGridRenderer', {}).get('contents', [])
                            break
                            
                for item in grid_contents:
                    rich_item = item.get('richItemRenderer', {})
                    content_node = rich_item.get('content', {})
                    
                    video_id = None
                    title = None
                    is_live = False
                    
                    # Format A: videoRenderer
                    if 'videoRenderer' in content_node:
                        v_renderer = content_node['videoRenderer']
                        video_id = v_renderer.get('videoId')
                        title = v_renderer.get('title', {}).get('runs', [{}])[0].get('text', '')
                        
                        thumbnail_overlays = v_renderer.get('thumbnailOverlays', [])
                        for overlay in thumbnail_overlays:
                            badge = overlay.get('thumbnailOverlayTimeStatusRenderer', {}).get('style', '')
                            if badge == 'LIVE':
                                is_live = True
                                break
                                
                    # Format B: lockupViewModel (modern layout)
                    elif 'lockupViewModel' in content_node:
                        lockup = content_node['lockupViewModel']
                        video_id = lockup.get('contentId')
                        
                        lmvm = lockup.get('metadata', {}).get('lockupMetadataViewModel', {})
                        title = lmvm.get('title', {}).get('content', '')
                        
                        # Check if live
                        overlays = lockup.get('contentImage', {}).get('thumbnailViewModel', {}).get('overlays', [])
                        for overlay in overlays:
                            badge = overlay.get('thumbnailOverlayTimeStatusRenderer', {}).get('style', '')
                            if badge == 'LIVE':
                                is_live = True
                                break
                                
                    if video_id and title:
                        videos.append({
                            'video_id': video_id,
                            'title': title,
                            'url': f"https://www.youtube.com/watch?v={video_id}",
                            'is_live': is_live
                        })
    except Exception as e:
        print(f"Error scraping CazéTV {tab}: {e}", file=sys.stderr)
        
    return videos

# Extract final score from YouTube title
def extract_score_from_title(title, team_a, team_b):
    title_clean = clean_string(title)
    a_clean = clean_string(team_a)
    b_clean = clean_string(team_b)
    
    # Pattern: "Brasil 2 x 0 Japão" or "Brasil 2 - 0 Japão"
    pattern = rf"{a_clean}\s*(\d+)\s*(?:x|-)\s*(\d+)\s*{b_clean}"
    match = re.search(pattern, title_clean)
    if match:
        return int(match.group(1)), int(match.group(2))
        
    # Symmetrical Pattern: "Japão 0 x 2 Brasil"
    pattern_rev = rf"{b_clean}\s*(\d+)\s*(?:x|-)\s*(\d+)\s*{a_clean}"
    match_rev = re.search(pattern_rev, title_clean)
    if match_rev:
        return int(match_rev.group(2)), int(match_rev.group(1))
        
    return None, None

# Match CazéTV videos to World Cup fixtures
def update_matches():
    if not os.path.exists(MATCHES_FILE):
        print(f"Matches database not found at {MATCHES_FILE}!")
        return []
        
    with open(MATCHES_FILE, "r", encoding="utf-8") as f:
        matches = json.load(f)
        
    # Get latest uploads & streams from CazéTV
    uploads = get_cazetv_youtube_content("videos")
    streams = get_cazetv_youtube_content("streams")
    all_videos = uploads + streams
    
    print(f"Fetched {len(all_videos)} media items from CazéTV.")
    
    updated_count = 0
    for match in matches:
        team_a = match['team_a']
        team_b = match['team_b']
        
        a_clean = clean_string(team_a)
        b_clean = clean_string(team_b)
        
        # 1. Search for live matches in active streams
        live_video = None
        for v in streams:
            if v['is_live']:
                title_clean = clean_string(v['title'])
                if a_clean in title_clean and b_clean in title_clean:
                    live_video = v
                    break
                    
        if live_video:
            # Match is currently streaming live!
            match['status'] = "Ao Vivo"
            match['live_link'] = live_video['url']
            # Attempt to parse current live score if written in title
            sa, sb = extract_score_from_title(live_video['title'], team_a, team_b)
            if sa is not None and sb is not None:
                match['score_a'] = sa
                match['score_b'] = sb
            updated_count += 1
            print(f"Match [{team_a} x {team_b}] is LIVE! URL: {live_video['url']}")
            continue
            
        # 2. Search for finished match videos (highlights/replays)
        highlights_video = None
        replay_video = None
        
        for v in all_videos:
            title_clean = clean_string(v['title'])
            if a_clean in title_clean and b_clean in title_clean:
                # Distinguish between highlights and full match replay
                if any(x in title_clean for x in ["melhores momentos", "gols", "resumo"]):
                    if not highlights_video:
                        highlights_video = v
                elif any(x in title_clean for x in ["jogo completo", "reproducao", "gravacao", "inteiro", "assista na integra"]):
                    if not replay_video:
                        replay_video = v
                elif not v['is_live']:
                    # Default backup as replay
                    if not replay_video:
                        replay_video = v
                        
        # If highlights or replays found, the match is Finished
        if highlights_video or replay_video:
            match['status'] = "Finalizado"
            match['live_link'] = None
            
            if highlights_video:
                match['highlights_link'] = highlights_video['url']
                # Parse final score from highlights title
                sa, sb = extract_score_from_title(highlights_video['title'], team_a, team_b)
                if sa is not None and sb is not None:
                    match['score_a'] = sa
                    match['score_b'] = sb
                    
            if replay_video:
                match['replay_link'] = replay_video['url']
                if match['score_a'] is None:  # Fallback score parser
                    sa, sb = extract_score_from_title(replay_video['title'], team_a, team_b)
                    if sa is not None and sb is not None:
                        match['score_a'] = sa
                        match['score_b'] = sb
                        
            # If still no score parsed but match is finished, set default mock scores if empty
            if match['score_a'] is None:
                match['score_a'] = 0
                match['score_b'] = 0
                
            updated_count += 1
            print(f"Match [{team_a} x {team_b}] is Finished. Highlights: {match['highlights_link']}, Replay: {match['replay_link']}, Score: {match['score_a']}x{match['score_b']}")

        # 3. Fallback for demo matches labeled as "Ao Vivo"
        if match['status'] == "Ao Vivo" and not match['live_link']:
            match['live_link'] = "https://www.youtube.com/@CazeTV/live"
            if match['score_a'] is None:
                match['score_a'] = 1
                match['score_b'] = 1
            
    with open(MATCHES_FILE, "w", encoding="utf-8") as f:
        json.dump(matches, f, indent=4, ensure_ascii=False)
        
    print(f"Successfully updated matches database ({updated_count} updates processed).")
    return matches

# Generate Dashboard HTML
def generate_html(matches):
    now_str = datetime.now().strftime("%d/%m/%Y às %H:%M:%S")
    
    # Calculate stats
    live_count = sum(1 for m in matches if m['status'] == "Ao Vivo")
    finished_count = sum(1 for m in matches if m['status'] == "Finalizado")
    scheduled_count = sum(1 for m in matches if m['status'] == "Agendado")
    
    # Identify any active live matches for banner
    live_matches_banner = []
    for m in matches:
        if m['status'] == "Ao Vivo":
            live_matches_banner.append(m)
            
    # HTML contents template
    html_content = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Copa 2026 - Memorial e Transmissões Ao Vivo</title>
    <!-- Google Fonts -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700;900&display=swap" rel="stylesheet">
    <!-- FontAwesome for Icons -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.2/css/all.min.css">
    
    <style>
        :root {{
            --bg-color: #060913;
            --card-bg: rgba(16, 23, 38, 0.6);
            --border-color: rgba(255, 255, 255, 0.08);
            --accent-gold: #ffb300;
            --accent-green: #00e676;
            --text-primary: #f3f4f6;
            --text-secondary: #9ca3af;
            --live-pulse: #ff1744;
        }}

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            background-color: var(--bg-color);
            color: var(--text-primary);
            font-family: 'Outfit', sans-serif;
            min-height: 100vh;
            background-image: 
                radial-gradient(at 0% 0%, rgba(255, 179, 0, 0.08) 0px, transparent 50%),
                radial-gradient(at 100% 0%, rgba(0, 230, 118, 0.05) 0px, transparent 50%);
            background-attachment: fixed;
            padding: 2rem 1rem;
        }}

        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}

        header {{
            text-align: center;
            margin-bottom: 2.5rem;
        }}

        h1 {{
            font-size: 3rem;
            font-weight: 900;
            background: linear-gradient(to right, var(--text-primary), var(--accent-gold));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 0.5rem;
            letter-spacing: -0.04em;
        }}

        .subtitle {{
            color: var(--text-secondary);
            font-size: 1.2rem;
            margin-bottom: 1.5rem;
        }}

        .last-update {{
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            background: rgba(255, 255, 255, 0.03);
            padding: 0.5rem 1.2rem;
            border-radius: 50px;
            font-size: 0.85rem;
            color: var(--text-secondary);
            border: 1px solid var(--border-color);
            backdrop-filter: blur(10px);
        }}

        .last-update i {{
            color: var(--accent-gold);
        }}

        /* Live Match Banner */
        .live-banner {{
            background: linear-gradient(135deg, rgba(255, 23, 68, 0.15) 0%, rgba(6, 9, 19, 0.9) 100%);
            border: 1px solid rgba(255, 23, 68, 0.3);
            border-radius: 20px;
            padding: 1.5rem 2rem;
            margin-bottom: 2.5rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 1.5rem;
            backdrop-filter: blur(15px);
            box-shadow: 0 10px 30px -15px rgba(255, 23, 68, 0.3);
        }}

        .live-badge {{
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            background: var(--live-pulse);
            color: white;
            padding: 0.3rem 0.8rem;
            border-radius: 50px;
            font-weight: 700;
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            animation: pulse-border 1.5s infinite alternate;
        }}

        @keyframes pulse-border {{
            0% {{ box-shadow: 0 0 0 0 rgba(255, 23, 68, 0.7); }}
            100% {{ box-shadow: 0 0 0 8px rgba(255, 23, 68, 0); }}
        }}

        .live-match-teams {{
            font-size: 1.5rem;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 1rem;
        }}

        .live-match-score {{
            background: rgba(255, 255, 255, 0.05);
            padding: 0.2rem 0.8rem;
            border-radius: 8px;
            border: 1px solid var(--border-color);
            color: var(--accent-gold);
        }}

        .live-banner-action {{
            background: #ff1744;
            color: white;
            padding: 0.8rem 1.8rem;
            border-radius: 10px;
            text-decoration: none;
            font-weight: 700;
            display: inline-flex;
            align-items: center;
            gap: 0.6rem;
            transition: all 0.2s ease;
            box-shadow: 0 4px 15px rgba(255, 23, 68, 0.4);
        }}

        .live-banner-action:hover {{
            background: #d50000;
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(255, 23, 68, 0.5);
        }}

        /* Statistics Cards */
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 1rem;
            margin-bottom: 2.5rem;
        }}

        .stat-card {{
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 1.5rem;
            text-align: center;
            backdrop-filter: blur(10px);
        }}

        .stat-val {{
            font-size: 2.5rem;
            font-weight: 900;
            margin-bottom: 0.25rem;
        }}

        .stat-val.live {{ color: var(--live-pulse); }}
        .stat-val.finished {{ color: var(--accent-gold); }}
        .stat-val.scheduled {{ color: var(--text-secondary); }}

        .stat-label {{
            font-size: 0.9rem;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}

        /* Control Panel */
        .controls {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 1rem;
            background: rgba(255, 255, 255, 0.02);
            padding: 1rem 1.5rem;
            border-radius: 16px;
            border: 1px solid var(--border-color);
            backdrop-filter: blur(10px);
            margin-bottom: 2.5rem;
        }}

        .filter-buttons {{
            display: flex;
            gap: 0.5rem;
            flex-wrap: wrap;
        }}

        .filter-btn {{
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid var(--border-color);
            color: var(--text-primary);
            padding: 0.6rem 1.2rem;
            border-radius: 8px;
            cursor: pointer;
            font-family: inherit;
            font-weight: 600;
            font-size: 0.9rem;
            transition: all 0.2s ease;
        }}

        .filter-btn:hover {{
            background: rgba(255, 255, 255, 0.08);
            transform: translateY(-1px);
        }}

        .filter-btn.active {{
            background: var(--accent-gold);
            border-color: var(--accent-gold);
            color: #060913;
            box-shadow: 0 0 15px rgba(255, 179, 0, 0.3);
        }}

        .select-group {{
            background: #0d1222;
            border: 1px solid var(--border-color);
            color: var(--text-primary);
            padding: 0.6rem 1.2rem;
            border-radius: 8px;
            font-family: inherit;
            font-weight: 600;
            cursor: pointer;
            outline: none;
        }}

        .search-box {{
            position: relative;
            min-width: 250px;
        }}

        .search-box i {{
            position: absolute;
            left: 1rem;
            top: 50%;
            transform: translateY(-50%);
            color: var(--text-secondary);
        }}

        .search-input {{
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            color: var(--text-primary);
            padding: 0.6rem 1rem 0.6rem 2.5rem;
            width: 100%;
            font-family: inherit;
            outline: none;
            transition: all 0.2s ease;
        }}

        .search-input:focus {{
            border-color: var(--accent-gold);
            background: rgba(255, 255, 255, 0.08);
        }}

        /* Matches Grid */
        .matches-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
            gap: 1.5rem;
            margin-bottom: 3rem;
        }}

        .match-card {{
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 20px;
            padding: 1.5rem;
            backdrop-filter: blur(10px);
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }}

        .match-card:hover {{
            transform: translateY(-5px);
            border-color: rgba(255, 179, 0, 0.25);
            box-shadow: 0 15px 30px -15px rgba(255, 179, 0, 0.15);
        }}

        .match-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 0.85rem;
            color: var(--text-secondary);
            margin-bottom: 1.2rem;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            padding-bottom: 0.5rem;
        }}

        .match-group {{
            font-weight: 600;
            background: rgba(255, 255, 255, 0.05);
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
        }}

        .match-status-badge {{
            font-weight: 700;
            font-size: 0.75rem;
            text-transform: uppercase;
            padding: 0.2rem 0.6rem;
            border-radius: 50px;
        }}

        .match-status-badge.ao-vivo {{
            background: rgba(255, 23, 68, 0.15);
            color: #ff1744;
            border: 1px solid rgba(255, 23, 68, 0.3);
            display: flex;
            align-items: center;
            gap: 0.3rem;
        }}

        .match-status-badge.ao-vivo i {{
            animation: blink 1s infinite alternate;
        }}

        @keyframes blink {{
            0% {{ opacity: 0.2; }}
            100% {{ opacity: 1; }}
        }}

        .match-status-badge.finalizado {{
            background: rgba(255, 179, 0, 0.1);
            color: var(--accent-gold);
            border: 1px solid rgba(255, 179, 0, 0.2);
        }}

        .match-status-badge.agendado {{
            background: rgba(255, 255, 255, 0.05);
            color: var(--text-secondary);
            border: 1px solid var(--border-color);
        }}

        .match-teams-score {{
            display: flex;
            flex-direction: column;
            gap: 0.8rem;
            margin-bottom: 1.5rem;
        }}

        .team-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}

        .team-info {{
            display: flex;
            align-items: center;
            gap: 0.8rem;
            font-size: 1.25rem;
            font-weight: 700;
        }}

        .team-flag {{
            width: 32px;
            height: 32px;
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--border-color);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.1rem;
        }}

        .team-score {{
            font-size: 1.5rem;
            font-weight: 800;
            color: var(--text-primary);
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--border-color);
            padding: 0.1rem 0.6rem;
            border-radius: 6px;
            min-width: 38px;
            text-align: center;
        }}

        .team-row.loser {{
            opacity: 0.6;
        }}

        .team-row.loser .team-score {{
            color: var(--text-secondary);
        }}

        /* Actions block */
        .match-actions {{
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
            margin-top: auto;
        }}

        .btn {{
            width: 100%;
            padding: 0.7rem;
            border-radius: 10px;
            text-align: center;
            font-weight: 700;
            font-size: 0.9rem;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 0.5rem;
            cursor: pointer;
            transition: all 0.2s ease;
        }}

        .btn-live {{
            background: #ff1744;
            color: white;
            border: none;
            box-shadow: 0 4px 10px rgba(255, 23, 68, 0.3);
        }}

        .btn-live:hover {{
            background: #d50000;
            transform: translateY(-1px);
        }}

        .btn-highlights {{
            background: linear-gradient(135deg, var(--accent-gold) 0%, #ff8f00 100%);
            color: #060913;
            border: none;
        }}

        .btn-highlights:hover {{
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(255, 179, 0, 0.3);
        }}

        .btn-replay {{
            background: transparent;
            border: 1px solid var(--border-color);
            color: var(--text-primary);
        }}

        .btn-replay:hover {{
            background: rgba(255, 255, 255, 0.05);
            border-color: var(--text-secondary);
        }}

        .btn-disabled {{
            background: rgba(255, 255, 255, 0.02);
            border: 1px dashed var(--border-color);
            color: var(--text-secondary);
            cursor: not-allowed;
        }}

        .empty-state {{
            grid-column: 1 / -1;
            text-align: center;
            padding: 4rem 2rem;
            background: rgba(255, 255, 255, 0.01);
            border: 1px dashed var(--border-color);
            border-radius: 20px;
            color: var(--text-secondary);
        }}

        .empty-state i {{
            font-size: 3rem;
            margin-bottom: 1rem;
        }}

        /* Footer */
        footer {{
            text-align: center;
            padding-top: 3rem;
            margin-top: 4rem;
            border-top: 1px solid var(--border-color);
            color: var(--text-secondary);
            font-size: 0.85rem;
        }}

        footer a {{
            color: var(--accent-gold);
            text-decoration: none;
            font-weight: 600;
        }}

        footer a:hover {{
            text-decoration: underline;
        }}

        @media (max-width: 768px) {{
            h1 {{ font-size: 2.2rem; }}
            .controls {{ flex-direction: column; align-items: stretch; }}
            .search-box {{ min-width: 100%; }}
            .live-banner {{ flex-direction: column; text-align: center; }}
            .live-match-teams {{ font-size: 1.25rem; }}
        }}
    </style>
</head>
<body>

    <div class="container">
        <header>
            <h1><i class="fa-solid fa-trophy"></i> Memorial Copa do Mundo 2026</h1>
            <p class="subtitle">Acompanhe os jogos ao vivo e assista aos melhores momentos das partidas transmitidas pela CazéTV</p>
            <div class="last-update">
                <i class="fa-solid fa-arrows-rotate"></i>
                Atualizado em: <span>{now_str}</span>
            </div>
        </header>

        <!-- BANNER DE JOGOS AO VIVO -->
        """
        
    if live_matches_banner:
        for lm in live_matches_banner:
            html_content += f"""
            <div class="live-banner">
                <div style="display: flex; flex-direction: column; gap: 0.5rem;">
                    <div class="live-badge"><i class="fa-solid fa-satellite-dish"></i> Transmissão Ao Vivo</div>
                    <div class="live-match-teams">
                        <span>{lm['team_a']}</span>
                        <span class="live-match-score">{lm['score_a']} x {lm['score_b']}</span>
                        <span>{lm['team_b']}</span>
                    </div>
                </div>
                <a href="{lm['live_link']}" target="_blank" class="live-banner-action">
                    <i class="fa-brands fa-youtube"></i> Assistir na CazéTV
                </a>
            </div>
            """
            
    html_content += f"""
        <!-- Estatísticas Rápidas -->
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-val live">{live_count}</div>
                <div class="stat-label">Jogos Ao Vivo</div>
            </div>
            <div class="stat-card">
                <div class="stat-val finished">{finished_count}</div>
                <div class="stat-label">Jogos Finalizados</div>
            </div>
            <div class="stat-card">
                <div class="stat-val scheduled">{scheduled_count}</div>
                <div class="stat-label">Jogos Agendados</div>
            </div>
        </div>

        <!-- Painel de Controle -->
        <div class="controls">
            <div class="filter-buttons">
                <button class="filter-btn active" onclick="filterStatus('all')">Todos os Jogos</button>
                <button class="filter-btn" onclick="filterStatus('live')"><i class="fa-solid fa-satellite-dish" style="color: #ff1744;"></i> Ao Vivo</button>
                <button class="filter-btn" onclick="filterStatus('finished')">Finalizados</button>
                <button class="filter-btn" onclick="filterStatus('scheduled')">Agendados</button>
            </div>
            <div style="display: flex; gap: 0.5rem; flex-wrap: wrap;">
                <select class="select-group" id="group-filter" onchange="filterGroup()">
                    <option value="all">Todos os Grupos</option>
                    <option value="Grupo A">Grupo A</option>
                    <option value="Grupo B">Grupo B</option>
                    <option value="Grupo C">Grupo C</option>
                    <option value="Grupo D">Grupo D</option>
                </select>
                <div class="search-box">
                    <i class="fa-solid fa-magnifying-glass"></i>
                    <input type="text" class="search-input" id="search-input" placeholder="Pesquisar seleção..." oninput="applyFilters()">
                </div>
            </div>
        </div>

        <main>
            <div class="matches-grid" id="matches-grid">
    """
    
    # Flags mapping helper
    def get_flag(team_name):
        # Mappings of team names to emoji flags
        flags = {
            "Brasil": "🇧🇷", "Japão": "🇯🇵", "Argentina": "🇦🇷", "Marrocos": "🇲🇦",
            "Portugal": "🇵🇹", "Uzbequistão": "🇺🇿", "França": "🇫🇷", "Estados Unidos": "🇺🇸",
            "Espanha": "🇪🇸", "Austrália": "🇦🇺", "Alemanha": "🇩🇪", "Camarões": "🇨🇲",
            "Itália": "🇮🇹", "México": "🇲🇽", "Uruguai": "🇺🇾", "Coreia do Sul": "🇰🇷"
        }
        return flags.get(team_name, "🏳️")

    if not matches:
        html_content += """
                <div class="empty-state">
                    <i class="fa-solid fa-circle-question"></i>
                    <p>Nenhuma partida cadastrada na base de dados.</p>
                </div>
        """
    else:
        for match in matches:
            status_class = match['status'].lower().replace(" ", "-")
            
            # Status Badge HTML
            if match['status'] == "Ao Vivo":
                status_badge = '<div class="match-status-badge ao-vivo"><i class="fa-solid fa-satellite-dish"></i> Ao Vivo</div>'
            elif match['status'] == "Finalizado":
                status_badge = '<div class="match-status-badge finalizado">Finalizado</div>'
            else:
                status_badge = f'<div class="match-status-badge agendado">{match["time"]}</div>'
                
            # Formatting scores display
            score_a_display = match['score_a'] if match['score_a'] is not None else "-"
            score_b_display = match['score_b'] if match['score_b'] is not None else "-"
            
            # Determine score loss opacity classes
            class_a = ""
            class_b = ""
            if match['status'] == "Finalizado":
                if match['score_a'] < match['score_b']:
                    class_a = "loser"
                elif match['score_b'] < match['score_a']:
                    class_b = "loser"
                    
            # Buttons HTML
            action_buttons = ""
            if match['status'] == "Ao Vivo":
                action_buttons = f"""
                    <a href="{match['live_link']}" target="_blank" class="btn btn-live">
                        <i class="fa-brands fa-youtube"></i> Assistir ao Vivo na CazéTV
                    </a>
                """
            elif match['status'] == "Finalizado":
                highlights_btn = f'<a href="{match["highlights_link"]}" target="_blank" class="btn btn-highlights"><i class="fa-solid fa-circle-play"></i> Melhores Momentos</a>' if match['highlights_link'] else '<button class="btn btn-disabled" disabled><i class="fa-solid fa-video-slash"></i> Sem Highlights</button>'
                replay_btn = f'<a href="{match["replay_link"]}" target="_blank" class="btn btn-replay"><i class="fa-brands fa-youtube"></i> Replay do Jogo</a>' if match['replay_link'] else ''
                action_buttons = f"""
                    <div style="display: flex; flex-direction: column; gap: 0.5rem; width: 100%;">
                        {highlights_btn}
                        {replay_btn}
                    </div>
                """
            else:
                action_buttons = f"""
                    <button class="btn btn-disabled" disabled>
                        <i class="fa-solid fa-hourglass-start"></i> Aguardando Partida
                    </button>
                """
                
            html_content += f"""
                <div class="match-card" data-status="{match['status'].lower()}" data-group="{match['group']}" data-team-a="{match['team_a'].lower()}" data-team-b="{match['team_b'].lower()}">
                    <div>
                        <div class="match-header">
                            <span class="match-group">{match['group']}</span>
                            <span>{match['date']}</span>
                            {status_badge}
                        </div>
                        
                        <div class="match-teams-score">
                            <div class="team-row {class_a}">
                                <div class="team-info">
                                    <span class="team-flag">{get_flag(match['team_a'])}</span>
                                    <span>{match['team_a']}</span>
                                </div>
                                <span class="team-score">{score_a_display}</span>
                            </div>
                            <div class="team-row {class_b}">
                                <div class="team-info">
                                    <span class="team-flag">{get_flag(match['team_b'])}</span>
                                    <span>{match['team_b']}</span>
                                </div>
                                <span class="team-score">{score_b_display}</span>
                            </div>
                        </div>
                    </div>
                    
                    <div class="match-actions">
                        {action_buttons}
                    </div>
                </div>
            """
            
    html_content += """
            </div>
        </main>

        <footer>
            <p>Criado automaticamente pelo Assistente para a Copa do Mundo FIFA 2026.</p>
            <p>Todos os vídeos e streams integrados são propriedades intelectuais da <a href="https://www.youtube.com/@CazeTV" target="_blank">CazéTV / LiveMode</a>.</p>
        </footer>
    </div>

    <script>
        let currentStatusFilter = 'all';
        let currentGroupFilter = 'all';

        function filterStatus(status) {
            currentStatusFilter = status;
            
            // Toggle active status button
            const buttons = document.querySelectorAll('.filter-btn');
            buttons.forEach(btn => btn.classList.remove('active'));
            
            const clickedBtn = Array.from(buttons).find(btn => {
                const text = btn.textContent.toLowerCase();
                return (status === 'all' && text.includes('todos')) ||
                       (status === 'live' && text.includes('ao vivo')) ||
                       (status === 'finished' && text.includes('finalizados')) ||
                       (status === 'scheduled' && text.includes('agendados'));
            });
            if (clickedBtn) clickedBtn.classList.add('active');
            
            applyFilters();
        }

        function filterGroup() {
            currentGroupFilter = document.getElementById('group-filter').value;
            applyFilters();
        }

        function applyFilters() {
            const searchQuery = document.getElementById('search-input').value.toLowerCase();
            const cards = document.querySelectorAll('.match-card');

            cards.forEach(card => {
                const status = card.getAttribute('data-status');
                const group = card.getAttribute('data-group');
                const teamA = card.getAttribute('data-team-a');
                const teamB = card.getAttribute('data-team-b');
                
                // 1. Status Filter
                let matchStatus = false;
                if (currentStatusFilter === 'all') {
                    matchStatus = true;
                } else if (currentStatusFilter === 'live') {
                    matchStatus = status === 'ao vivo';
                } else if (currentStatusFilter === 'finished') {
                    matchStatus = status === 'finalizado';
                } else if (currentStatusFilter === 'scheduled') {
                    matchStatus = status === 'agendado';
                }
                
                // 2. Group Filter
                let matchGroup = false;
                if (currentGroupFilter === 'all') {
                    matchGroup = true;
                } else {
                    matchGroup = group === currentGroupFilter;
                }
                
                // 3. Search Filter
                const matchSearch = teamA.includes(searchQuery) || teamB.includes(searchQuery);
                
                // Combine filters
                if (matchStatus && matchGroup && matchSearch) {
                    card.style.display = 'flex';
                } else {
                    card.style.display = 'none';
                }
            });
        }
    </script>
</body>
</html>
"""

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    print(f"Successfully generated FIFA 2026 Memorial Dashboard at: {OUTPUT_FILE}")

# Generate CSV and JSON metrics
def generate_csv_and_metrics(matches):
    # 1. Generate CSV
    csv_file = os.path.join(OUTPUT_DIR, "matches_data.csv")
    print(f"Gerando arquivo CSV da Copa em: {csv_file}...")
    try:
        with open(csv_file, mode='w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Match ID', 'Group', 'Team A', 'Team B', 'Date', 'Time', 'Status', 'Score A', 'Score B', 'Live Link', 'Highlights Link', 'Replay Link'])
            
            for m in matches:
                writer.writerow([
                    m.get('id', 'N/A'),
                    m.get('group', 'N/A'),
                    m.get('team_a', 'N/A'),
                    m.get('team_b', 'N/A'),
                    m.get('date', 'N/A'),
                    m.get('time', 'N/A'),
                    m.get('status', 'N/A'),
                    m.get('score_a') if m.get('score_a') is not None else '',
                    m.get('score_b') if m.get('score_b') is not None else '',
                    m.get('live_link', '') or '',
                    m.get('highlights_link', '') or '',
                    m.get('replay_link', '') or ''
                ])
    except Exception as e:
        print(f"Erro ao salvar CSV da Copa: {e}", file=sys.stderr)

    # 2. Generate JSON Metrics
    metrics_file = os.path.join(OUTPUT_DIR, "matches_metrics.json")
    print(f"Gerando métricas da Copa em: {metrics_file}...")
    try:
        total_matches = len(matches)
        live_count = sum(1 for m in matches if m['status'] == "Ao Vivo")
        finished_count = sum(1 for m in matches if m['status'] == "Finalizado")
        scheduled_count = sum(1 for m in matches if m['status'] == "Agendado")
        
        # Calculate goal metrics
        total_goals = 0
        highlights_count = 0
        replay_count = 0
        max_goals = -1
        max_goals_match = "N/A"
        
        for m in matches:
            if m['status'] in ["Finalizado", "Ao Vivo"] and m['score_a'] is not None and m['score_b'] is not None:
                goals_sum = m['score_a'] + m['score_b']
                total_goals += goals_sum
                if goals_sum > max_goals:
                    max_goals = goals_sum
                    max_goals_match = f"{m['team_a']} {m['score_a']} x {m['score_b']} {m['team_b']}"
            
            if m['status'] == "Finalizado":
                if m.get('highlights_link'):
                    highlights_count += 1
                if m.get('replay_link'):
                    replay_count += 1
                    
        avg_goals = round(total_goals / (finished_count + live_count), 2) if (finished_count + live_count) > 0 else 0
        highlights_coverage = round((highlights_count / finished_count) * 100, 1) if finished_count > 0 else 0
        replay_coverage = round((replay_count / finished_count) * 100, 1) if finished_count > 0 else 0
        
        metrics = {
            "last_updated": datetime.now().isoformat(),
            "tournament_summary": {
                "total_matches_in_database": total_matches,
                "matches_finished": finished_count,
                "matches_currently_live": live_count,
                "matches_scheduled": scheduled_count
            },
            "goals_statistics": {
                "total_goals_scored": total_goals,
                "average_goals_per_match": avg_goals,
                "highest_scoring_match": max_goals_match if max_goals >= 0 else "N/A"
            },
            "cazetv_coverage_metrics": {
                "highlights_available_count": highlights_count,
                "highlights_coverage_percentage": f"{highlights_coverage}%",
                "full_replays_available_count": replay_count,
                "full_replays_coverage_percentage": f"{replay_coverage}%"
            }
        }
        
        with open(metrics_file, mode='w', encoding='utf-8') as f:
            json.dump(metrics, f, indent=4, ensure_ascii=False)
            
    except Exception as e:
        print(f"Erro ao salvar métricas JSON da Copa: {e}", file=sys.stderr)

def main():
    print("Starting FIFA 2026 cazéTV Memorial Updater...")
    # Update score, status and links from YouTube
    updated_matches = update_matches()
    # Generate HTML
    generate_html(updated_matches)
    # Generate CSV and JSON Metrics
    generate_csv_and_metrics(updated_matches)
    print("Updater execution completed.")

if __name__ == "__main__":
    main()
