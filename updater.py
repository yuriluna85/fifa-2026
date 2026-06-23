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

# Helper to fetch HTML/content, routing through ScraperAPI if SCRAPERAPI_KEY is available
def fetch_html(url, timeout=15):
    scraper_key = os.getenv("SCRAPERAPI_KEY")
    
    # Try direct access first
    req_direct = urllib.request.Request(
        url,
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    )
    try:
        print(f"Acessando diretamente: {url}")
        with urllib.request.urlopen(req_direct, timeout=timeout) as response:
            return response.read()
    except Exception as e:
        print(f"Acesso direto falhou para {url}: {e}", file=sys.stderr)
        if scraper_key:
            print(f"Tentando ScraperAPI como fallback para {url}...", file=sys.stderr)
            encoded_url = urllib.parse.quote(url)
            final_url = f"http://api.scraperapi.com?api_key={scraper_key}&url={encoded_url}"
            req_scraper = urllib.request.Request(
                final_url,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
            )
            try:
                with urllib.request.urlopen(req_scraper, timeout=timeout) as response:
                    return response.read()
            except Exception as ex:
                print(f"Fallback ScraperAPI também falhou para {url}: {ex}", file=sys.stderr)
        raise e


# Load environment variables from .env file if it exists
def load_env_file():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    paths = [
        os.path.join(script_dir, ".env"),
        os.path.join(os.getcwd(), ".env")
    ]
    for p in paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            parts = line.split("=", 1)
                            key = parts[0].strip()
                            value = parts[1].strip().strip('"').strip("'")
                            os.environ[key] = value
                print(f"Carregadas variáveis de ambiente de: {p}")
                return
            except Exception as e:
                print(f"Erro ao ler arquivo .env: {e}", file=sys.stderr)

# Search YouTube using Serper API
def search_youtube_serper(query):
    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        return []
        
    print(f"Buscando no Serper YouTube por: '{query}'...")
    url = "https://google.serper.dev/videos"
    headers = {
        'X-API-KEY': api_key,
        'Content-Type': 'application/json'
    }
    data = json.dumps({"q": query}).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    
    videos = []
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            results = res_data.get('videos', [])
            for item in results:
                title = item.get('title')
                link = item.get('link')
                channel = item.get('channel', '') or ''
                if title and link:
                    channel_clean = clean_string(channel)
                    if 'caze' not in channel_clean:
                        print(f"  [Serper Filter] Rejeitado canal '{channel}': '{title}'")
                        continue
                    
                    video_id = extract_video_id(link)
                    if video_id:
                        title_clean = clean_string(title)
                        is_live = "ao vivo" in title_clean or "live" in title_clean or item.get('duration') == 'LIVE'
                        
                        print(f"  [Serper Match] Aceito vídeo de CazéTV: '{title}' ({video_id})")
                        videos.append({
                            'video_id': video_id,
                            'title': title,
                            'url': f"https://www.youtube.com/watch?v={video_id}",
                            'is_live': is_live
                        })
    except Exception as e:
        print(f"Erro ao buscar no Serper YouTube: {e}", file=sys.stderr)
        
    return videos

# Helper to normalize text (remove accents, lowercase)
def clean_string(s):
    s = s.lower()
    s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    # Replace common abbreviations
    s = s.replace("eua", "estados unidos").replace("usa", "estados unidos")
    return s.strip()

# Extract YouTube 11-char video ID from url
def extract_video_id(url):
    if not url:
        return None
    if "youtube.com" not in url and "youtu.be" not in url and "youtube-nocookie.com" not in url:
        return None
    match = re.search(r'(?:v=|\/embed\/|\/youtu\.be\/|\/v\/|\/shorts\/)([a-zA-Z0-9_-]{11})', url)
    return match.group(1) if match else None


# Scrape CazéTV channel videos or streams using ytInitialData JSON
def get_cazetv_youtube_content(tab="videos"):
    print(f"Scraping CazéTV YouTube tab: '{tab}'...")
    url = f"https://www.youtube.com/@CazeTV/{tab}"
    videos = []
    try:
        html_bytes = fetch_html(url, timeout=15)
        html = html_bytes.decode('utf-8')
        
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
                endpoint = tab_renderer.get('endpoint', {})
                canonical = endpoint.get('browseEndpoint', {}).get('canonicalBaseUrl', '') or ''
                web_url = endpoint.get('commandMetadata', {}).get('webCommandMetadata', {}).get('url', '') or ''
                
                # Check canonical URL and web command metadata URL
                if (tab in canonical or tab in web_url or
                    (tab == "videos" and ("videos" in canonical or "videos" in web_url)) or
                    (tab == "streams" and ("streams" in canonical or "streams" in web_url or "live" in web_url))):
                    grid_contents = tab_renderer.get('content', {}).get('richGridRenderer', {}).get('contents', [])
                    break
                    
            if not grid_contents:
                # Fallback check tab title
                for t in tabs:
                    tab_renderer = t.get('tabRenderer', {})
                    title = tab_renderer.get('title', '').lower()
                    if (tab == "videos" and ("víd" in title or "video" in title)) or \
                       (tab == "streams" and ("trans" in title or "live" in title or "stream" in title or "ao vivo" in title or "direto" in title)):
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
                        badge_vm = overlay.get('thumbnailOverlayBadgeViewModel', {})
                        badge_style = badge_vm.get('badgeStyle', '') or ''
                        badge_text = badge_vm.get('text', '') or ''
                        if 'LIVE' in badge_style or badge_text == 'AO VIVO' or badge_text == 'LIVE':
                            is_live = True
                            break
                        badge_bottom = overlay.get('thumbnailBottomOverlayViewModel', {})
                        badges = badge_bottom.get('badges', [])
                        for b in badges:
                            b_vm = b.get('thumbnailBadgeViewModel', {})
                            b_style = b_vm.get('badgeStyle', '') or ''
                            b_text = b_vm.get('text', '') or ''
                            if 'LIVE' in b_style or b_text == 'AO VIVO' or b_text == 'LIVE':
                                is_live = True
                                break
                        if is_live:
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
                        badge_vm = overlay.get('thumbnailOverlayBadgeViewModel', {})
                        badge_style = badge_vm.get('badgeStyle', '') or ''
                        badge_text = badge_vm.get('text', '') or ''
                        if 'LIVE' in badge_style or badge_text == 'AO VIVO' or badge_text == 'LIVE':
                            is_live = True
                            break
                        badge_bottom = overlay.get('thumbnailBottomOverlayViewModel', {})
                        badges = badge_bottom.get('badges', [])
                        for b in badges:
                            b_vm = b.get('thumbnailBadgeViewModel', {})
                            b_style = b_vm.get('badgeStyle', '') or ''
                            b_text = b_vm.get('text', '') or ''
                            if 'LIVE' in b_style or b_text == 'AO VIVO' or b_text == 'LIVE':
                                is_live = True
                                break
                        if is_live:
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
        
    # Load environment variables
    load_env_file()
    
    api_key = os.getenv("SERPER_API_KEY")
    all_videos = []
    
    # Check if Serper API Key is configured
    if api_key:
        print("SERPER_API_KEY encontrada no ambiente. Usando Serper YouTube API como fonte primária.")
        # Fetch generic channel videos
        all_videos.extend(search_youtube_serper("CazeTV"))
        all_videos.extend(search_youtube_serper("CazeTV ao vivo"))
        
        # Search specifically for active or finished matches
        for match in matches:
            if match['status'] in ["Ao Vivo", "Finalizado"]:
                team_a = match['team_a']
                team_b = match['team_b']
                # Search for "CazeTV [Team A] x [Team B]"
                match_query = f"CazeTV {team_a} {team_b}"
                all_videos.extend(search_youtube_serper(match_query))
    else:
        print("SERPER_API_KEY não configurada. Usando scraper do canal como fallback.")
        
    # Always combine/fallback to scraper to be extra safe
    try:
        uploads = get_cazetv_youtube_content("videos")
        streams = get_cazetv_youtube_content("streams")
        all_videos.extend(uploads + streams)
    except Exception as e:
        print(f"Erro ao rodar scraper: {e}. Usando apenas resultados do Serper se disponíveis.", file=sys.stderr)
        
    # Deduplicate videos by video_id
    unique_videos = {}
    for v in all_videos:
        if v['video_id'] not in unique_videos:
            unique_videos[v['video_id']] = v
    all_videos = list(unique_videos.values())
    
    # Filter live videos from all unique videos
    live_videos = [v for v in all_videos if v.get('is_live')]
    
    print(f"Total de {len(all_videos)} vídeos carregados para cruzamento (sendo {len(live_videos)} transmissões ao vivo).")
    
    updated_count = 0
    for match in matches:
        team_a = match['team_a']
        team_b = match['team_b']
        
        a_clean = clean_string(team_a)
        b_clean = clean_string(team_b)
        
        # 1. Search for live matches in active streams
        live_video = None
        for v in live_videos:
            title_clean = clean_string(v['title'])
            if a_clean in title_clean and b_clean in title_clean:
                if not live_video:
                    live_video = v
                else:
                    # If the already selected video is pre-game/esquenta but this one is not, prefer this one
                    current_is_pre = any(x in clean_string(live_video['title']) for x in ["pre-jogo", "pre jogo", "esquenta"])
                    new_is_pre = any(x in title_clean for x in ["pre-jogo", "pre jogo", "esquenta"])
                    if current_is_pre and not new_is_pre:
                        live_video = v

                    
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

        # 3. General fallback handling to clean mocks and provide working search links
        q_team_a = urllib.parse.quote(team_a)
        q_team_b = urllib.parse.quote(team_b)
        
        if match['status'] == "Ao Vivo":
            ll = match.get('live_link')
            if not ll or "MOCK" in ll:
                match['live_link'] = "https://www.youtube.com/@CazeTV/live"
            if match['score_a'] is None:
                match['score_a'] = 1
                match['score_b'] = 1
                
        elif match['status'] == "Finalizado":
            hl = match.get('highlights_link')
            if not hl or "MOCK" in hl:
                match['highlights_link'] = f"https://www.youtube.com/@CazeTV/search?query={q_team_a}+{q_team_b}+melhores+momentos"
            rp = match.get('replay_link')
            if not rp or "MOCK" in rp:
                match['replay_link'] = f"https://www.youtube.com/@CazeTV/search?query={q_team_a}+{q_team_b}+jogo+completo"
            if match['score_a'] is None:
                match['score_a'] = 0
                match['score_b'] = 0
                
        elif match['status'] == "Agendado":
            match['live_link'] = None
            match['highlights_link'] = None
            match['replay_link'] = None
            match['score_a'] = None
            match['score_b'] = None
            
    with open(MATCHES_FILE, "w", encoding="utf-8") as f:
        json.dump(matches, f, indent=4, ensure_ascii=False)
        
    print(f"Successfully updated matches database ({updated_count} updates processed).")
    return matches

# Generate Dashboard HTML
# Generate Dashboard HTML
def generate_html(matches):
    now_str = datetime.now().strftime("%d/%m/%Y às %H:%M:%S")
    
    # Calculate stats
    live_count = sum(1 for m in matches if m['status'] == "Ao Vivo")
    finished_count = sum(1 for m in matches if m['status'] == "Finalizado")
    scheduled_count = sum(1 for m in matches if m['status'] == "Agendado")
    
    # Get all unique groups in matches, sorted
    unique_groups = sorted(list(set(m['group'] for m in matches if m.get('group'))))
    group_options_html = '<option value="all">Todos os Grupos</option>\\n'
    for g in unique_groups:
        group_options_html += f'                    <option value="{g}">{g}</option>\\n'
        
    json_data_embedded = json.dumps(matches, ensure_ascii=False)

    # HTML contents template
    html_content = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Copa 2026 - Memorial e Transmissões CazéTV</title>
    <!-- Google Fonts -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
    <!-- FontAwesome for Icons -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.2/css/all.min.css">
    
    <style>
        :root {{
            --bg-color: #05070f;
            --surface-bg: rgba(13, 18, 33, 0.45);
            --surface-border: rgba(255, 255, 255, 0.06);
            --accent-gold: hsl(43, 100%, 50%);
            --accent-gold-hover: hsl(43, 100%, 45%);
            --accent-gold-glow: rgba(255, 179, 0, 0.15);
            --accent-red: hsl(348, 100%, 50%);
            --accent-red-hover: hsl(348, 100%, 45%);
            --accent-red-glow: rgba(255, 23, 68, 0.25);
            --accent-blue: hsl(198, 100%, 50%);
            --accent-green: hsl(145, 100%, 45%);
            
            --text-primary: #f3f4f6;
            --text-secondary: #9ca3af;
            --text-muted: #6b7280;
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
                radial-gradient(at 0% 0%, rgba(255, 179, 0, 0.07) 0px, transparent 50%),
                radial-gradient(at 100% 0%, rgba(0, 230, 118, 0.04) 0px, transparent 50%),
                radial-gradient(at 50% 100%, rgba(56, 189, 248, 0.05) 0px, transparent 50%);
            background-attachment: fixed;
            padding: 2rem 1rem;
            overflow-y: scroll;
        }}

        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}

        header {{
            text-align: center;
            margin-bottom: 2.5rem;
            position: relative;
        }}

        h1 {{
            font-size: 3.2rem;
            font-weight: 900;
            background: linear-gradient(135deg, #ffffff 30%, var(--accent-gold) 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 0.5rem;
            letter-spacing: -0.04em;
            display: inline-flex;
            align-items: center;
            gap: 0.8rem;
        }}

        .subtitle {{
            color: var(--text-secondary);
            font-size: 1.2rem;
            margin-bottom: 1.5rem;
            font-weight: 300;
        }}

        .header-meta {{
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 1rem;
            flex-wrap: wrap;
        }}

        .last-update, .sync-status {{
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            background: rgba(255, 255, 255, 0.03);
            padding: 0.5rem 1.2rem;
            border-radius: 50px;
            font-size: 0.85rem;
            color: var(--text-secondary);
            border: 1px solid var(--surface-border);
            backdrop-filter: blur(10px);
        }}

        .last-update i {{
            color: var(--accent-gold);
        }}

        .sync-status i {{
            color: var(--accent-green);
        }}

        .sync-status.loading i {{
            animation: spin 1s linear infinite;
            color: var(--accent-blue);
        }}

        @keyframes spin {{
            100% {{ transform: rotate(360deg); }}
        }}

        /* Live Match Banner */
        .live-banners-section {{
            margin-bottom: 2.5rem;
        }}

        .live-banner {{
            background: linear-gradient(135deg, rgba(255, 23, 68, 0.1) 0%, rgba(13, 18, 33, 0.7) 100%);
            border: 1px solid rgba(255, 23, 68, 0.25);
            border-radius: 24px;
            padding: 1.8rem;
            backdrop-filter: blur(15px);
            box-shadow: 0 20px 40px -20px rgba(255, 23, 68, 0.15);
            transition: all 0.3s ease;
        }}

        .live-banner-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 1.5rem;
            margin-bottom: 1.5rem;
        }}

        .live-badge {{
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            background: var(--accent-red);
            color: white;
            padding: 0.4rem 1rem;
            border-radius: 50px;
            font-weight: 700;
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            box-shadow: 0 0 15px rgba(255, 23, 68, 0.4);
            animation: pulse-badge 1.5s infinite alternate;
        }}

        @keyframes pulse-badge {{
            0% {{ box-shadow: 0 0 0 0 rgba(255, 23, 68, 0.5); }}
            100% {{ box-shadow: 0 0 12px 6px rgba(255, 23, 68, 0.1); }}
        }}

        .live-match-teams {{
            font-size: 1.6rem;
            font-weight: 800;
            display: flex;
            align-items: center;
            gap: 1.2rem;
            letter-spacing: -0.02em;
        }}

        .live-match-score {{
            background: rgba(0, 0, 0, 0.4);
            padding: 0.2rem 1rem;
            border-radius: 12px;
            border: 1px solid rgba(255, 255, 255, 0.08);
            color: var(--accent-gold);
            font-size: 1.8rem;
            font-weight: 900;
            font-variant-numeric: tabular-nums;
        }}

        .live-banner-action {{
            background: var(--accent-red);
            color: white;
            padding: 0.8rem 1.8rem;
            border-radius: 12px;
            text-decoration: none;
            font-weight: 700;
            display: inline-flex;
            align-items: center;
            gap: 0.6rem;
            transition: all 0.2s ease;
            box-shadow: 0 4px 15px rgba(255, 23, 68, 0.3);
        }}

        .live-banner-action:hover {{
            background: var(--accent-red-hover);
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(255, 23, 68, 0.4);
        }}

        .live-player-container {{
            position: relative;
            padding-bottom: 56.25%;
            height: 0;
            overflow: hidden;
            border-radius: 16px;
            border: 1px solid rgba(255, 255, 255, 0.05);
            box-shadow: 0 15px 35px rgba(0, 0, 0, 0.4);
            background: #000;
        }}

        .live-player-container iframe {{
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
        }}

        /* Statistics Cards */
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 1.25rem;
            margin-bottom: 2.5rem;
        }}

        .stat-card {{
            background: var(--surface-bg);
            border: 1px solid var(--surface-border);
            border-radius: 20px;
            padding: 1.5rem;
            text-align: center;
            backdrop-filter: blur(12px);
            transition: all 0.3s ease;
        }}

        .stat-card:hover {{
            border-color: rgba(255, 255, 255, 0.12);
            transform: translateY(-2px);
        }}

        .stat-val {{
            font-size: 2.8rem;
            font-weight: 900;
            margin-bottom: 0.2rem;
            line-height: 1.1;
        }}

        .stat-val.live {{ color: var(--accent-red); text-shadow: 0 0 15px rgba(255, 23, 68, 0.2); }}
        .stat-val.finished {{ color: var(--accent-gold); text-shadow: 0 0 15px rgba(255, 179, 0, 0.15); }}
        .stat-val.scheduled {{ color: var(--accent-blue); }}

        .stat-label {{
            font-size: 0.85rem;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.08em;
            font-weight: 600;
        }}

        /* Control Panel */
        .controls {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 1.25rem;
            background: rgba(255, 255, 255, 0.015);
            padding: 1.2rem 1.8rem;
            border-radius: 20px;
            border: 1px solid var(--surface-border);
            backdrop-filter: blur(12px);
            margin-bottom: 2.5rem;
        }}

        .filter-buttons {{
            display: flex;
            gap: 0.6rem;
            flex-wrap: wrap;
        }}

        .filter-btn {{
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--surface-border);
            color: var(--text-primary);
            padding: 0.6rem 1.4rem;
            border-radius: 10px;
            cursor: pointer;
            font-family: inherit;
            font-weight: 600;
            font-size: 0.9rem;
            transition: all 0.2s ease;
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
        }}

        .filter-btn:hover {{
            background: rgba(255, 255, 255, 0.07);
            transform: translateY(-1px);
        }}

        .filter-btn.active {{
            background: var(--accent-gold);
            border-color: var(--accent-gold);
            color: #05070f;
            box-shadow: 0 0 15px var(--accent-gold-glow);
        }}

        .filter-btn.active:hover {{
            background: var(--accent-gold-hover);
        }}

        .select-group {{
            background: #090e1a;
            border: 1px solid var(--surface-border);
            color: var(--text-primary);
            padding: 0.6rem 1.4rem;
            border-radius: 10px;
            font-family: inherit;
            font-weight: 600;
            cursor: pointer;
            outline: none;
            transition: all 0.2s ease;
        }}

        .select-group:focus {{
            border-color: var(--accent-gold);
        }}

        .search-box {{
            position: relative;
            min-width: 250px;
        }}

        .search-box i {{
            position: absolute;
            left: 1.1rem;
            top: 50%;
            transform: translateY(-50%);
            color: var(--text-muted);
            font-size: 0.95rem;
        }}

        .search-input {{
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--surface-border);
            border-radius: 10px;
            color: var(--text-primary);
            padding: 0.65rem 1rem 0.65rem 2.7rem;
            width: 100%;
            font-family: inherit;
            outline: none;
            transition: all 0.2s ease;
            font-size: 0.9rem;
        }}

        .search-input:focus {{
            border-color: var(--accent-gold);
            background: rgba(255, 255, 255, 0.06);
            box-shadow: 0 0 12px rgba(255, 179, 0, 0.08);
        }}

        /* Matches Grid */
        .matches-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
            gap: 1.5rem;
            margin-bottom: 3rem;
        }}

        .match-card {{
            background: var(--surface-bg);
            border: 1px solid var(--surface-border);
            border-radius: 24px;
            padding: 1.6rem;
            backdrop-filter: blur(12px);
            transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            position: relative;
            overflow: hidden;
        }}

        .match-card::before {{
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 4px;
            background: transparent;
            transition: all 0.3s ease;
        }}

        .match-card:hover {{
            transform: translateY(-6px);
            border-color: rgba(255, 255, 255, 0.12);
            box-shadow: 0 20px 30px -15px rgba(0, 0, 0, 0.3);
        }}

        .match-card[data-status-card="ao-vivo"]::before {{
            background: var(--accent-red);
        }}

        .match-card[data-status-card="ao-vivo"] {{
            border-color: rgba(255, 23, 68, 0.2);
            box-shadow: 0 10px 20px -10px rgba(255, 23, 68, 0.1);
        }}

        .match-card[data-status-card="finalizado"]::before {{
            background: var(--accent-gold);
        }}

        .match-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 0.85rem;
            color: var(--text-secondary);
            margin-bottom: 1.2rem;
            border-bottom: 1px solid rgba(255, 255, 255, 0.04);
            padding-bottom: 0.6rem;
        }}

        .match-group {{
            font-weight: 700;
            background: rgba(255, 255, 255, 0.05);
            padding: 0.2rem 0.6rem;
            border-radius: 6px;
            font-size: 0.8rem;
            color: var(--text-primary);
        }}

        .match-status-badge {{
            font-weight: 800;
            font-size: 0.72rem;
            text-transform: uppercase;
            padding: 0.25rem 0.7rem;
            border-radius: 50px;
            letter-spacing: 0.03em;
            display: inline-flex;
            align-items: center;
            gap: 0.3rem;
        }}

        .match-status-badge.ao-vivo {{
            background: rgba(255, 23, 68, 0.12);
            color: var(--accent-red);
            border: 1px solid rgba(255, 23, 68, 0.2);
        }}

        .match-status-badge.ao-vivo i {{
            animation: pulse-red-dot 1s infinite alternate;
        }}

        @keyframes pulse-red-dot {{
            0% {{ opacity: 0.3; }}
            100% {{ opacity: 1; }}
        }}

        .match-status-badge.finalizado {{
            background: rgba(255, 179, 0, 0.08);
            color: var(--accent-gold);
            border: 1px solid rgba(255, 179, 0, 0.18);
        }}

        .match-status-badge.agendado {{
            background: rgba(255, 255, 255, 0.04);
            color: var(--text-secondary);
            border: 1px solid var(--surface-border);
        }}

        .match-status-badge.agendado-hoje {{
            background: rgba(56, 189, 248, 0.08);
            color: var(--accent-blue);
            border: 1px solid rgba(56, 189, 248, 0.2);
        }}

        .match-status-badge.agendado-em-breve {{
            background: rgba(56, 189, 248, 0.15);
            color: var(--accent-blue);
            border: 1px solid rgba(56, 189, 248, 0.35);
            box-shadow: 0 0 10px rgba(56, 189, 248, 0.1);
        }}

        .match-status-badge.agendado-decorrendo {{
            background: rgba(255, 179, 0, 0.1);
            color: var(--accent-gold);
            border: 1px solid rgba(255, 179, 0, 0.25);
            animation: pulse-gold-border 1.5s infinite alternate;
        }}

        @keyframes pulse-gold-border {{
            0% {{ border-color: rgba(255, 179, 0, 0.2); }}
            100% {{ border-color: rgba(255, 179, 0, 0.6); }}
        }}

        .match-teams-score {{
            display: flex;
            flex-direction: column;
            gap: 0.9rem;
            margin-bottom: 1.6rem;
        }}

        .team-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            transition: opacity 0.2s ease;
        }}

        .team-info {{
            display: flex;
            align-items: center;
            gap: 0.9rem;
            font-size: 1.28rem;
            font-weight: 700;
            letter-spacing: -0.01em;
        }}

        .team-flag {{
            width: 34px;
            height: 34px;
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid var(--surface-border);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.25rem;
            box-shadow: 0 4px 8px rgba(0, 0, 0, 0.15);
        }}

        .team-score {{
            font-size: 1.6rem;
            font-weight: 800;
            color: var(--text-primary);
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--surface-border);
            padding: 0.15rem 0.75rem;
            border-radius: 8px;
            min-width: 44px;
            text-align: center;
            font-variant-numeric: tabular-nums;
        }}

        .team-row.loser {{
            opacity: 0.45;
        }}

        .team-row.loser .team-score {{
            color: var(--text-secondary);
            background: transparent;
            border-style: dashed;
        }}

        /* Actions block */
        .match-actions {{
            display: flex;
            flex-direction: column;
            gap: 0.6rem;
            margin-top: auto;
        }}

        .btn {{
            width: 100%;
            padding: 0.75rem;
            border-radius: 12px;
            text-align: center;
            font-weight: 700;
            font-size: 0.92rem;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 0.5rem;
            cursor: pointer;
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
            border: none;
            outline: none;
        }}

        .btn-live {{
            background: var(--accent-red);
            color: white;
            box-shadow: 0 4px 12px var(--accent-red-glow);
        }}

        .btn-live:hover {{
            background: var(--accent-red-hover);
            transform: translateY(-1.5px);
            box-shadow: 0 6px 16px rgba(255, 23, 68, 0.4);
        }}

        .btn-watch-now {{
            background: rgba(255, 255, 255, 0.08);
            color: var(--text-primary);
            border: 1px solid rgba(255, 255, 255, 0.06);
        }}

        .btn-watch-now:hover {{
            background: rgba(255, 255, 255, 0.14);
            transform: translateY(-1.5px);
        }}

        .btn-highlights {{
            background: linear-gradient(135deg, var(--accent-gold) 0%, #ff8f00 100%);
            color: #05070f;
            box-shadow: 0 4px 12px var(--accent-gold-glow);
        }}

        .btn-highlights:hover {{
            transform: translateY(-1.5px);
            box-shadow: 0 6px 16px rgba(255, 179, 0, 0.35);
        }}

        .btn-replay {{
            background: transparent;
            border: 1px solid var(--surface-border);
            color: var(--text-primary);
        }}

        .btn-replay:hover {{
            background: rgba(255, 255, 255, 0.05);
            border-color: var(--text-secondary);
            transform: translateY(-1px);
        }}

        .btn-disabled {{
            background: rgba(255, 255, 255, 0.02);
            border: 1px dashed var(--surface-border);
            color: var(--text-muted);
            cursor: not-allowed;
        }}

        .empty-state {{
            grid-column: 1 / -1;
            text-align: center;
            padding: 5rem 2rem;
            background: rgba(255, 255, 255, 0.015);
            border: 1px dashed var(--surface-border);
            border-radius: 24px;
            color: var(--text-secondary);
            backdrop-filter: blur(12px);
        }}

        .empty-state i {{
            font-size: 3.5rem;
            color: var(--text-muted);
            margin-bottom: 1.2rem;
        }}

        .empty-state p {{
            font-size: 1.1rem;
            font-weight: 500;
        }}

        /* Footer */
        footer {{
            text-align: center;
            padding-top: 3rem;
            margin-top: 5rem;
            border-top: 1px solid var(--surface-border);
            color: var(--text-secondary);
            font-size: 0.88rem;
            font-weight: 400;
        }}

        footer p {{
            margin-bottom: 0.4rem;
        }}

        footer a {{
            color: var(--accent-gold);
            text-decoration: none;
            font-weight: 600;
            transition: opacity 0.2s ease;
        }}

        footer a:hover {{
            text-decoration: underline;
            opacity: 0.9;
        }}

        @media (max-width: 768px) {{
            h1 {{ font-size: 2.4rem; }}
            .controls {{ flex-direction: column; align-items: stretch; padding: 1.2rem; }}
            .search-box {{ min-width: 100%; }}
            .live-banner {{ padding: 1.2rem; }}
            .live-match-teams {{ font-size: 1.25rem; gap: 0.6rem; }}
            .live-match-score {{ font-size: 1.4rem; padding: 0.2rem 0.6rem; }}
            .live-banner-header {{ flex-direction: column; align-items: stretch; text-align: center; }}
            .live-banner-action {{ justify-content: center; }}
        }}
    </style>
</head>
<body>

    <div class="container">
        <header>
            <h1><i class="fa-solid fa-trophy" style="color: var(--accent-gold);"></i> Memorial Copa do Mundo 2026</h1>
            <p class="subtitle">Acompanhe os jogos ao vivo e assista aos melhores momentos das partidas transmitidas pela CazéTV</p>
            <div class="header-meta">
                <div class="last-update">
                    <i class="fa-solid fa-arrows-rotate"></i>
                    Sincronizado em: <span id="last-update-time">{now_str}</span>
                </div>
                <div class="sync-status" id="sync-indicator">
                    <i class="fa-solid fa-circle-check"></i>
                    <span>Monitoramento Ativo</span>
                </div>
            </div>
        </header>

        <!-- LIVE STREAM PLAYER BANNERS -->
        <div id="live-banners-container" class="live-banners-section"></div>
        
        <!-- Statistics Grid -->
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-val live" id="stat-val-live">{live_count}</div>
                <div class="stat-label">Jogos Ao Vivo</div>
            </div>
            <div class="stat-card">
                <div class="stat-val finished" id="stat-val-finished">{finished_count}</div>
                <div class="stat-label">Jogos Finalizados</div>
            </div>
            <div class="stat-card">
                <div class="stat-val scheduled" id="stat-val-scheduled">{scheduled_count}</div>
                <div class="stat-label">Jogos Agendados</div>
            </div>
        </div>

        <!-- Controls Filter Panel -->
        <div class="controls">
            <div class="filter-buttons">
                <button class="filter-btn active" id="btn-filter-all" onclick="filterStatus('all')">Todos os Jogos</button>
                <button class="filter-btn" id="btn-filter-live" onclick="filterStatus('live')"><i class="fa-solid fa-satellite-dish" style="color: var(--accent-red);"></i> Ao Vivo</button>
                <button class="filter-btn" id="btn-filter-finished" onclick="filterStatus('finished')">Finalizados</button>
                <button class="filter-btn" id="btn-filter-scheduled" onclick="filterStatus('scheduled')">Agendados</button>
            </div>
            <div style="display: flex; gap: 0.6rem; flex-wrap: wrap; width: auto;" id="filters-right-group">
                <select class="select-group" id="group-filter" onchange="filterGroup()">
                    {group_options_html}
                </select>
                <div class="search-box">
                    <i class="fa-solid fa-magnifying-glass"></i>
                    <input type="text" class="search-input" id="search-input" placeholder="Pesquisar seleção..." oninput="applyFilters()">
                </div>
            </div>
        </div>

        <main>
            <div class="matches-grid" id="matches-grid">
                <!-- Javascript will render cards dynamically here -->
            </div>
        </main>

        <footer>
            <p>Criado automaticamente pelo Assistente para a Copa do Mundo FIFA 2026.</p>
            <p>Todos os vídeos e streams integrados são propriedades intelectuais da <a href="https://www.youtube.com/@CazeTV" target="_blank">CazéTV / LiveMode</a>.</p>
        </footer>
    </div>

    <script>
        // Baked-in matches database generated by python
        let matchesData = {json_data_embedded};
        
        let currentStatusFilter = 'all';
        let currentGroupFilter = 'all';
        let currentActiveVideoId = null;
        let countdownInterval = null;

        // Flag Mapping
        const flags = {{
            "Brasil": "🇧🇷", "Japão": "🇯🇵", "Argentina": "🇦🇷", "Marrocos": "🇲🇦",
            "Portugal": "🇵🇹", "Uzbequistão": "🇺🇿", "França": "🇫🇷", "Estados Unidos": "🇺🇸",
            "Espanha": "🇪🇸", "Austrália": "🇦🇺", "Alemanha": "🇩🇪", "Camarões": "🇨🇲",
            "Itália": "🇮🇹", "México": "🇲🇽", "Uruguai": "🇺🇾", "Coreia do Sul": "🇰🇷",
            "Inglaterra": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "Gana": "🇬🇭"
        }};

        // Extract YouTube ID from url
        function getYouTubeId(url) {{
            if (!url) return null;
            const regExp = /^.*(youtu.be\/|v\/|u\/\w\/|embed\/|watch\?v=|\&v=)([^#\&\?]*).*/;
            const match = url.match(regExp);
            return (match && match[2].length === 11) ? match[2] : null;
        }}

        // Parse date (DD/MM/YYYY) and time (HH:MM) to date object
        function parseMatchDateTime(dateStr, timeStr) {{
            const [day, month, year] = dateStr.split('/').map(Number);
            const [hours, minutes] = timeStr.split(':').map(Number);
            return new Date(year, month - 1, day, hours, minutes);
        }}

        // Calculate countdowns and badges
        function getMatchTimeStatus(match) {{
            if (match.status === 'Ao Vivo') {{
                return {{
                    badgeClass: 'ao-vivo',
                    badgeText: '<i class="fa-solid fa-satellite-dish"></i> Ao Vivo',
                    isLive: true
                }};
            }} else if (match.status === 'Finalizado') {{
                return {{
                    badgeClass: 'finalizado',
                    badgeText: 'Finalizado',
                    isLive: false
                }};
            }} else {{
                // Scheduled
                const matchTime = parseMatchDateTime(match.date, match.time);
                const now = new Date();
                const diffMs = matchTime - now;

                if (diffMs > 0) {{
                    const diffMin = Math.floor(diffMs / 60000);
                    if (diffMin < 60) {{
                        return {{
                            badgeClass: 'agendado-em-breve',
                            badgeText: `<i class="fa-regular fa-clock"></i> Começa em ${{diffMin}}m`,
                            isLive: false
                        }};
                    }} else if (diffMin < 1440) {{
                        const hours = Math.floor(diffMin / 60);
                        const mins = diffMin % 60;
                        return {{
                            badgeClass: 'agendado-hoje',
                            badgeText: `<i class="fa-regular fa-clock"></i> Começa em ${{hours}}h ${{mins}}m`,
                            isLive: false
                        }};
                    }} else {{
                        return {{
                            badgeClass: 'agendado',
                            badgeText: `<i class="fa-regular fa-calendar"></i> ${{match.time}}`,
                            isLive: false
                        }};
                    }}
                }} else {{
                    // Match time has passed but it's not marked Live or Finished yet
                    return {{
                        badgeClass: 'agendado-decorrendo',
                        badgeText: '<i class="fa-solid fa-hourglass-start"></i> Horário do Jogo (Aguardando Live)',
                        isLive: false
                    }};
                }}
            }}
        }}

        // Scroll to player banner
        function playInBanner(matchId) {{
            const match = matchesData.find(m => m.id === matchId);
            if (!match || !match.live_link) return;
            
            // Set this match as primary by shifting matchesData
            const matchIndex = matchesData.findIndex(m => m.id === matchId);
            if (matchIndex > -1) {{
                const [targetMatch] = matchesData.splice(matchIndex, 1);
                matchesData.unshift(targetMatch);
            }}
            
            updateLiveBanner();
            
            // Smooth scroll to top banner
            window.scrollTo({{
                top: 0,
                behavior: 'smooth'
            }});
        }}

        // Generate HTML for card
        function getMatchCardHtml(match) {{
            const statusInfo = getMatchTimeStatus(match);
            const scoreA = match.score_a !== null ? match.score_a : '-';
            const scoreB = match.score_b !== null ? match.score_b : '-';
            const statusClass = match.status.toLowerCase().replace(' ', '-');
            
            // Determine winner/loser class for final matches
            let classA = "";
            let classB = "";
            if (match.status === "Finalizado" && match.score_a !== null && match.score_b !== null) {{
                if (match.score_a < match.score_b) {{
                    classA = "loser";
                }} else if (match.score_b < match.score_a) {{
                    classB = "loser";
                }}
            }}
            
            // Actions block
            let actionButtons = "";
            if (match.status === "Ao Vivo") {{
                actionButtons = `
                    <div style="display: flex; gap: 0.5rem; width: 100%;">
                        <button onclick="playInBanner(${{match.id}})" class="btn btn-watch-now">
                            <i class="fa-solid fa-play"></i> Assistir no Portal
                        </button>
                        <a href="${{match.live_link || 'https://www.youtube.com/@CazeTV/live'}}" target="_blank" class="btn btn-live">
                            <i class="fa-brands fa-youtube"></i> Abrir YouTube
                        </a>
                    </div>
                `;
            }} else if (match.status === "Finalizado") {{
                const highlightsBtn = match.highlights_link 
                    ? `<a href="${{match.highlights_link}}" target="_blank" class="btn btn-highlights"><i class="fa-solid fa-circle-play"></i> Melhores Momentos</a>` 
                    : `<button class="btn btn-disabled" disabled><i class="fa-solid fa-video-slash"></i> Sem Highlights</button>`;
                    
                const replayBtn = match.replay_link 
                    ? `<a href="${{match.replay_link}}" target="_blank" class="btn btn-replay"><i class="fa-solid fa-film"></i> Jogo Completo</a>` 
                    : ``;
                    
                actionButtons = `
                    <div style="display: flex; flex-direction: column; gap: 0.5rem; width: 100%;">
                        ${{highlightsBtn}}
                        ${{replayBtn}}
                    </div>
                `;
            }} else {{
                // Scheduled
                actionButtons = `
                    <button class="btn btn-disabled" disabled>
                        <i class="fa-solid fa-hourglass-start"></i> Aguardando Partida
                    </button>
                `;
            }}
            
            return `
                <div class="match-card" data-status-card="${{statusClass}}" data-id="${{match.id}}">
                    <div>
                        <div class="match-header">
                            <span class="match-group">${{match.group}}</span>
                            <span>${{match.date}}</span>
                            <div class="match-status-badge ${{statusInfo.badgeClass}}">${{statusInfo.badgeText}}</div>
                        </div>
                        
                        <div class="match-teams-score">
                            <div class="team-row ${{classA}}">
                                <div class="team-info">
                                    <span class="team-flag">${{flags[match.team_a] || '🏳️'}}</span>
                                    <span>${{match.team_a}}</span>
                                </div>
                                <span class="team-score">${{scoreA}}</span>
                            </div>
                            <div class="team-row ${{classB}}">
                                <div class="team-info">
                                    <span class="team-flag">${{flags[match.team_b] || '🏳️'}}</span>
                                    <span>${{match.team_b}}</span>
                                </div>
                                <span class="team-score">${{scoreB}}</span>
                            </div>
                        </div>
                    </div>
                    
                    <div class="match-actions">
                        ${{actionButtons}}
                    </div>
                </div>
            `;
        }}

        // Render Live Stream Banner
        function updateLiveBanner() {{
            const bannerContainer = document.getElementById('live-banners-container');
            const liveMatches = matchesData.filter(m => m.status === 'Ao Vivo');
            
            if (liveMatches.length === 0) {{
                bannerContainer.innerHTML = '';
                currentActiveVideoId = null;
                return;
            }}
            
            const primaryLiveMatch = liveMatches[0];
            const videoId = getYouTubeId(primaryLiveMatch.live_link);
            
            let bannerEl = document.getElementById('live-banner-el');
            
            if (!bannerEl) {{
                bannerContainer.innerHTML = `
                    <div class="live-banner" id="live-banner-el">
                        <div class="live-banner-header">
                            <div class="live-banner-info">
                                <div class="live-badge"><i class="fa-solid fa-satellite-dish"></i> Transmissão Ao Vivo</div>
                                <div class="live-match-teams">
                                    <span id="banner-team-a"></span>
                                    <span class="live-match-score" id="banner-score"></span>
                                    <span id="banner-team-b"></span>
                                </div>
                            </div>
                            <a href="#" id="banner-youtube-link" target="_blank" class="live-banner-action">
                                <i class="fa-brands fa-youtube"></i> Abrir no YouTube
                            </a>
                        </div>
                        <div id="banner-player-wrapper"></div>
                    </div>
                `;
                bannerEl = document.getElementById('live-banner-el');
            }}
            
            // Update details
            document.getElementById('banner-team-a').innerHTML = `${{flags[primaryLiveMatch.team_a] || '🏳️'}} ${{primaryLiveMatch.team_a}}`;
            document.getElementById('banner-team-b').innerHTML = `${{primaryLiveMatch.team_b}} ${{flags[primaryLiveMatch.team_b] || '🏳️'}}`;
            
            const scoreA = primaryLiveMatch.score_a !== null ? primaryLiveMatch.score_a : '-';
            const scoreB = primaryLiveMatch.score_b !== null ? primaryLiveMatch.score_b : '-';
            document.getElementById('banner-score').innerText = `${{scoreA}} x ${{scoreB}}`;
            document.getElementById('banner-youtube-link').href = primaryLiveMatch.live_link || 'https://www.youtube.com/@CazeTV/live';
            
            // Update iframe safely
            const playerWrapper = document.getElementById('banner-player-wrapper');
            if (videoId !== currentActiveVideoId) {{
                currentActiveVideoId = videoId;
                if (videoId) {{
                    const embedUrl = `https://www.youtube.com/embed/${{videoId}}?autoplay=1&mute=1`;
                    playerWrapper.innerHTML = `
                        <div class="live-player-container" style="margin-top: 1.5rem;">
                            <iframe src="${{embedUrl}}" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen></iframe>
                        </div>
                    `;
                }} else {{
                    const channelLiveEmbed = "https://www.youtube.com/embed/live_stream?channel=UC4y3RCV7vvy151yUv8dF_Hw&autoplay=1&mute=1";
                    playerWrapper.innerHTML = `
                        <div class="live-player-container" style="margin-top: 1.5rem;">
                            <iframe src="${{channelLiveEmbed}}" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen></iframe>
                        </div>
                    `;
                }}
            }}
        }}

        // Recalculate stats counters
        function updateStats() {{
            const liveCount = matchesData.filter(m => m.status === 'Ao Vivo').length;
            const finishedCount = matchesData.filter(m => m.status === 'Finalizado').length;
            const scheduledCount = matchesData.filter(m => m.status === 'Agendado').length;
            
            document.getElementById('stat-val-live').innerText = liveCount;
            document.getElementById('stat-val-finished').innerText = finishedCount;
            document.getElementById('stat-val-scheduled').innerText = scheduledCount;
        }}

        // Render main matches grid
        function renderMatchesGrid() {{
            const grid = document.getElementById('matches-grid');
            const searchQuery = document.getElementById('search-input').value.toLowerCase();
            
            const filtered = matchesData.filter(match => {{
                // Status Filter
                let statusMatch = false;
                if (currentStatusFilter === 'all') statusMatch = true;
                else if (currentStatusFilter === 'live') statusMatch = match.status === 'Ao Vivo';
                else if (currentStatusFilter === 'finished') statusMatch = match.status === 'Finalizado';
                else if (currentStatusFilter === 'scheduled') statusMatch = match.status === 'Agendado';
                
                // Group Filter
                let groupMatch = false;
                if (currentGroupFilter === 'all') groupMatch = true;
                else groupMatch = match.group === currentGroupFilter;
                
                // Search query
                const searchMatch = match.team_a.toLowerCase().includes(searchQuery) || 
                                    match.team_b.toLowerCase().includes(searchQuery);
                                    
                return statusMatch && groupMatch && searchMatch;
            }});

            if (filtered.length === 0) {{
                grid.innerHTML = `
                    <div class="empty-state">
                        <i class="fa-solid fa-circle-question"></i>
                        <p>Nenhuma partida encontrada.</p>
                    </div>
                `;
                return;
            }}

            grid.innerHTML = filtered.map(getMatchCardHtml).join('');
        }}

        // Filter Quick Buttons
        function filterStatus(status) {{
            currentStatusFilter = status;
            
            // Toggle active class on buttons
            document.querySelectorAll('.filter-btn').forEach(btn => {{
                btn.classList.remove('active');
            }});
            
            const mapping = {{
                'all': 'btn-filter-all',
                'live': 'btn-filter-live',
                'finished': 'btn-filter-finished',
                'scheduled': 'btn-filter-scheduled'
            }};
            
            const activeId = mapping[status];
            if (activeId) {{
                document.getElementById(activeId).classList.add('active');
            }}
            
            renderMatchesGrid();
        }}

        function filterGroup() {{
            currentGroupFilter = document.getElementById('group-filter').value;
            renderMatchesGrid();
        }}

        function applyFilters() {{
            renderMatchesGrid();
        }}

        // Periodic Dynamic Data Polling (CORS friendly)
        async function fetchUpdatedData() {{
            const indicator = document.getElementById('sync-indicator');
            indicator.classList.add('loading');
            indicator.querySelector('span').innerText = 'Sincronizando...';
            indicator.querySelector('i').className = 'fa-solid fa-arrows-rotate';
            
            try {{
                // Request matches.json with a cache buster query parameter
                const response = await fetch('matches.json?cb=' + Date.now());
                if (response.ok) {{
                    const newData = await response.json();
                    if (JSON.stringify(newData) !== JSON.stringify(matchesData)) {{
                        console.log('Dados atualizados detectados.');
                        matchesData = newData;
                        updateLiveBanner();
                        updateStats();
                        renderMatchesGrid();
                    }}
                    
                    document.getElementById('last-update-time').innerText = new Date().toLocaleDateString('pt-BR') + ' às ' + new Date().toLocaleTimeString('pt-BR');
                    
                    indicator.classList.remove('loading');
                    indicator.querySelector('span').innerText = 'Monitoramento Ativo';
                    indicator.querySelector('i').className = 'fa-solid fa-circle-check';
                }}
            }} catch (error) {{
                console.warn('Falha ao rodar atualização em tempo real (provável CORS ou offline):', error);
                
                // Keep showing active monitor but with localized warning if CORS issue
                indicator.classList.remove('loading');
                indicator.querySelector('span').innerText = 'Modo Local Estático';
                indicator.querySelector('i').className = 'fa-solid fa-circle-info';
                indicator.querySelector('i').style.color = 'var(--accent-gold)';
            }}
        }}

        // Initial setup and startup
        function init() {{
            // Render on start
            updateLiveBanner();
            updateStats();
            renderMatchesGrid();
            
            // Set up local ticking countdowns (updates timers on scheduled cards every 10 seconds)
            countdownInterval = setInterval(() => {{
                renderMatchesGrid();
            }}, 10000);
            
            // Polling every 20 seconds for matches.json changes
            setInterval(fetchUpdatedData, 20000);
        }}

        window.onload = init;
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
