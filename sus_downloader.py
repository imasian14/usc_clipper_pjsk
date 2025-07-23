import requests
import os
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

# always 4 digits to replace x with level id
sekai_url = "https://storage.sekai.best/sekai-jp-assets/music/music_score/{song_id}_01/{difficulty}.txt"
difficulties = ["expert", "master", "append"]

en_musics_url = "https://sekai-world.github.io/sekai-master-db-en-diff/musics.json"
jp_musics_url = "https://sekai-world.github.io/sekai-master-db-diff/musics.json"
usctool_path = os.path.join(os.path.dirname(__file__), "usctool.exe")

def sanitize_filename(name: str) -> str:
    # Remove characters not allowed in Windows filenames
    return re.sub(r'[\\/:*?"<>|]', '', name)

def run(musics_url: str, url_template: str):
    musics_json = requests.get(musics_url).json()
    os.makedirs("official_charts_sus", exist_ok=True)
    os.makedirs("official_charts_usc", exist_ok=True)
    for music in musics_json:
        for difficulty in difficulties:   
            song_id = music['id']
            song_title = music['title']
            safe_title = sanitize_filename(song_title)
            target_file_name = f"./official_charts_sus/{song_id}_{safe_title}_{difficulty}.sus"
            if difficulty != "append":
                url = url_template.format(song_id=str(song_id).zfill(4), difficulty=difficulty)
            else:
                try:
                    url = url_template.format(song_id=str(song_id).zfill(4), difficulty=difficulty)
                except:
                    print(f"no append for {safe_title}")

            # if the file already exists, skip downloading
            if os.path.exists(target_file_name):
                print(f"File {target_file_name} already exists, skipping download.")
            else:
                # download the file
                print(f"Downloading {url}")
                level = requests.get(url)
                if level.status_code == 200:
                    level_text = level.text
                    with open(target_file_name, "w", encoding="utf-8") as f:
                        f.write(level_text)
                    # now convert to usc
                    subprocess.run([usctool_path, "convert", target_file_name, f"./official_charts_usc/{song_id}_{safe_title}_{difficulty}.usc"])
                else:
                    if difficulty == "append":
                        print(f"Append for {safe_title} probably doesn't exist ({level.status_code})")
                    else:
                        print(f"Failed to download {url}, status code: {level.status_code}")

run(en_musics_url, sekai_url)
run(jp_musics_url, sekai_url)