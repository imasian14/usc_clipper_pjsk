import numpy as np
import pandas as pd
import json
import os
from flask import Flask, render_template_string, request, send_file, redirect, url_for, send_from_directory

version_number = 1.1

def process_chart(file_content, start_measure, end_measure):
    start_beat = float(start_measure * 4)
    end_beat = float(end_measure * 4)

    def usc_to_string(file_content):
        return file_content.decode("utf-8")

    string_usc = usc_to_string(file_content)
    usc_json = json.loads(string_usc)
    objects = usc_json["usc"]["objects"]

    # utilities
    def return_type(event, type):
        return event["type"] == type

    def trimmer(object):
        if object["beat"] < start_beat or object["beat"] > end_beat:
            return False
        else:
            return True
        
    def trimmer_only_start(object):
        if object["beat"] < start_beat:
            return False
        else:
            return True
        
    def trimmer_only_end(object):
        if object["beat"] > end_beat:
            return False
        else:
            return True 

    def shifter(object):
        new_beat = object["beat"] - start_beat
        return {
            **object,
            "beat": new_beat
        }
    
    def deNull(object):
        object2 = {**object}
        if "critical" in object:
            if object["critical"] is None:
                object2["critical"] = False

        if "direction" in object:
            if object["direction"] is None:
                del object2["direction"]

        return object2


    bpm_objects = [x for x in objects if return_type(x, "bpm")]

    # offset finding
    offset_seconds = float(0)
    bpm_df = pd.DataFrame({"beat":[0], "bpm":[0]})
    for i, bpm_object in enumerate(bpm_objects):
        beat = float(bpm_object["beat"])
        bpm = float(bpm_object["bpm"])
        bpm_df.loc[i] = [beat, bpm]

    offset_finding_table = bpm_df.copy()
    beat_list = np.array(offset_finding_table["beat"].to_list())
    offset_bpm_beat = beat_list[beat_list <= start_beat].max()
    start_bpm = float(offset_finding_table.loc[offset_finding_table["beat"] == offset_bpm_beat, "bpm"].iloc[0])
    offset_finding_table.loc[offset_finding_table.index.max() + 1] = [start_beat, start_bpm]
    offset_finding_table = offset_finding_table.sort_values(by=['beat']).reset_index(drop=True)
    bpm_objects.append({"beat": start_beat, "bpm": start_bpm, "type": "bpm"})
    bpm_objects.sort(key=lambda x: x["beat"])

    shifted_bpm_objects = [shifter(x) for x in bpm_objects if trimmer(x)]

    for i in range(len(offset_finding_table["beat"].to_list())):
        if offset_finding_table.at[i, "beat"] < start_beat:
            offset_seconds += ((offset_finding_table.at[i+1, "beat"] - offset_finding_table.at[i, "beat"]) / offset_finding_table.at[i, "bpm"]) * 60
        elif offset_finding_table.at[i, "beat"] >= start_beat:
            break

    def add_default_to_timeScaleGroup_if_needed(speed_object):
        for change in speed_object["changes"]:
            if change["beat"] == 0:
                return speed_object
        new_changes = [{'beat': 0.0, 'timeScale': 1.0}]
        new_changes.extend(speed_object["changes"])
        return {
            **speed_object,
            "changes": new_changes
        }

    speed_objects = [add_default_to_timeScaleGroup_if_needed(x) for x in objects if return_type(x, "timeScaleGroup")]

    def get_initial_speed(speed_object):
        events_before_start_beat = [x for x in speed_object['changes'] if x['beat'] <= start_beat]
        max_event = events_before_start_beat[0]
        for event in events_before_start_beat:
            if event['beat'] > max_event['beat']:
                max_event = event
        return max_event['timeScale']

    def fix_timeScaleGroup(speed_object):
        initial_speed = get_initial_speed(speed_object)
        speed_changes = speed_object["changes"]
        speed_changes.append({"beat": start_beat, "timeScale": initial_speed})
        speed_changes.sort(key=lambda x: x["beat"])
        return speed_changes

    fixed_speed_changes = [fix_timeScaleGroup(x) for x in speed_objects]

    def speed_trimmer_and_shifter(speed_changes):
        trimmed_speed_group = []
        for speed_change in speed_changes:
            if trimmer(speed_change):
                speed_change = shifter(speed_change)
                trimmed_speed_group.append(speed_change)
        return trimmed_speed_group
    

    trimmed_shifted_speed_changes = [speed_trimmer_and_shifter(x) for x in fixed_speed_changes]

    def new_speed_object(speed_object, trimmed_shifted_speed_change):
        return {
            **speed_object,
            "changes": trimmed_shifted_speed_change
        }

    trimmed_shifted_speed_objects = []
    for k in range(len(speed_objects)):
        trimmed_shifted_speed_objects.append(new_speed_object(speed_objects[k], trimmed_shifted_speed_changes[k]))

    single_objects = [x for x in objects if return_type(x, "single")]
    shifted_single_objects = [deNull(shifter(x)) for x in single_objects if trimmer(x)]
            
    guide_objects = [x for x in objects if return_type(x, "guide")]

    def trim_guide(guide_object):
        for midpoint in guide_object["midpoints"]:
            if trimmer(midpoint) == False:
                return False
        return True

    def guide_trimmer_and_shifter(guide_object):
        new_midpoint_list = []
        new_guide_object = guide_object
        guide_midpoints = guide_object["midpoints"]
        for midpoint in guide_midpoints:
            midpoint = shifter(midpoint)
            new_midpoint_list.append(midpoint)
        return {
            **new_guide_object,
            "midpoints": new_midpoint_list
        }

    shifted_guide_objects = [deNull(guide_trimmer_and_shifter(x)) for x in guide_objects if trim_guide(x)]

    slide_objects = [x for x in objects if return_type(x, "slide")]

    def check_slide(slide_object):
        slide_midpoints = slide_object["connections"]
        for midpoint in slide_midpoints:
            if trimmer_only_start(midpoint) == False:
                return False
        for midpoint in slide_midpoints:
            if trimmer_only_end(midpoint):
                return True
        return False

    def shift_slide(slide_object):
        slide_midpoints = slide_object["connections"]
        end_midpoint = None
        for midpoint in slide_midpoints:
            if midpoint['type'] == 'end':
                end_midpoint = deNull(midpoint)
        
        if end_midpoint is None:
            raise Exception("Slide did not contain an ending, this should never happen")
        should_cap_ending = end_midpoint["beat"] > end_beat
        adjusted_midpoints = []
        all_midpoints_except_end = [x for x in slide_midpoints if x['type'] != 'end']
        for midpoint in all_midpoints_except_end:
            new_midpoint = deNull(shifter(midpoint))
            adjusted_midpoints.append(new_midpoint)
        if should_cap_ending:
            capped_ending = {
                **end_midpoint,
                "beat": (end_beat - start_beat),
                "judgeType": "none"
            }
            if 'direction' in capped_ending:
                del capped_ending['direction']
            adjusted_midpoints.append(capped_ending)
        else:
            adjusted_midpoints.append(deNull(shifter(end_midpoint)))
        return {
            **slide_object,
            "connections": adjusted_midpoints
        }

    trimmed_shifted_slide_objects = [shift_slide(x) for x in slide_objects if check_slide(x)]

    final_objects = []
    final_objects.extend(shifted_bpm_objects)
    final_objects.extend(trimmed_shifted_speed_objects)
    final_objects.extend(shifted_single_objects)
    final_objects.extend(shifted_guide_objects)
    final_objects.extend(trimmed_shifted_slide_objects)

    final_obj = {
        "usc": {
            "objects": final_objects,
            "offset": offset_seconds
        },
        "version": 2
    }

    return json.dumps(final_obj, indent=2)

app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Chart Clipper</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        :root {
            --primary: #4f8cff;
            --background: #f7f9fb;
            --card: #fff;
            --border: #e3e7ee;
            --text: #222;
            --accent: #3498DB;
        }
        body {
            background: var(--background);
            font-family: 'Inter', 'Segoe UI', Arial, sans-serif;
            margin: 0;
            color: var(--text);
        }
        .container {
            max-width: 600px;
            margin: 40px auto;
            background: var(--card);
            border-radius: 16px;
            box-shadow: 0 4px 24px rgba(79,140,255,0.08);
            padding: 32px 28px 24px 28px;
            border: 1px solid var(--border);
        }
        h1 {
            font-size: 2.2rem;
            font-weight: 700;
            margin-bottom: 0.5em;
            color: var(--primary);
            letter-spacing: -1px;
        }
        p {
            margin-top: 0.5em;
            margin-bottom: 1.2em;
            font-size: 1.05rem;
        }
        form {
            margin-top: 1.5em;
        }
        label {
            font-weight: 500;
            margin-bottom: 0.3em;
            display: block;
        }
        input[type="number"], input[type="file"], input[type="text"] {
            width: 100%;
            padding: 0.5em 0.7em;
            margin-bottom: 1.2em;
            border-radius: 8px;
            border: 1px solid var(--border);
            font-size: 1rem;
            background: var(--background);
            transition: border-color 0.2s;
        }
        input[type="number"]:focus, input[type="file"]:focus, input[type="text"]:focus {
            border-color: var(--primary);
            outline: none;
        }
        button[type="submit"] {
            background: var(--primary);
            color: #fff;
            border: none;
            border-radius: 8px;
            padding: 0.7em 1.5em;
            font-size: 1.1rem;
            font-weight: 600;
            cursor: pointer;
            box-shadow: 0 2px 8px rgba(79,140,255,0.08);
            transition: background 0.2s;
            margin-top: 0.5em;
        }
        button[type="submit"]:hover {
            background: var(--accent);
            color: var(--text);
        }
        .expander {
            margin-bottom: 1.5em;
        }
        details[open] summary {
            color: var(--primary);
        }
        summary {
            font-weight: 600;
            font-size: 1.05rem;
            cursor: pointer;
            padding: 0.5em 0;
        }
        details {
            background: var(--background);
            border-radius: 8px;
            border: 1px solid var(--border);
            padding: 0.7em 1em;
            margin-bottom: 1em;
        }
        .file-list {
            margin-bottom: 1.5em;
            position: relative;
        }
        .usc-dropdown {
            position: absolute;
            top: 60px;
            left: 0;
            width: 100%;
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 8px;
            box-shadow: 0 2px 12px rgba(79,140,255,0.08);
            z-index: 10;
            max-height: 220px;
            overflow-y: auto;
            display: none;
        }
        .usc-dropdown.visible {
            display: block;
        }
        .usc-option {
            padding: 0.7em 1em;
            cursor: pointer;
            border-bottom: 1px solid var(--border);
        }
        .usc-option:last-child {
            border-bottom: none;
        }
        .usc-option:hover, .usc-option.selected {
            background: var(--background);
            color: var(--primary);
        }
        .download-link {
            margin-top: 2em;
            text-align: center;
        }
        .download-link a {
            background: var(--accent);
            color: var(--text);
            padding: 0.7em 1.2em;
            border-radius: 8px;
            font-weight: 600;
            text-decoration: none;
            box-shadow: 0 2px 8px rgba(255,179,71,0.08);
            transition: background 0.2s;
        }
        .download-link a:hover {
            background: var(--primary);
            color: #fff;
        }
        .error {
            color: #d32f2f;
            background: #ffeaea;
            border-radius: 8px;
            padding: 0.7em 1em;
            margin-top: 1em;
            font-weight: 500;
        }
        @media (max-width: 700px) {
            .container {
                max-width: 98vw;
                padding: 18px 8px 16px 8px;
            }
            h1 {
                font-size: 1.5rem;
            }
        }
    </style>
</head>
<body>
<div class="container">
    <h1>Chart Clipper</h1>
    <p>Select an existing chart, select start and end measures, and download the clipped chart. Alternatively, upload your own .usc file.</p>
    <p>Please ping <span style="color:var(--accent);font-weight:600">@imasian.</span> on Discord if chart is not available.</p>
    <p style="font-size:0.98rem;color:#888;">Version: {{ version_number }}</p>
    <form method="POST" enctype="multipart/form-data">
        <div class="file-list">
            <label for="usc_search">Search PJSK charts:</label>
            <input type="text" id="usc_search" name="usc_search" autocomplete="off" placeholder="Type to search charts..." style="width:100%;margin-bottom:0.7em;">
            <div id="usc_dropdown" class="usc-dropdown"></div>
            <input type="hidden" name="selected_usc" id="selected_usc" value="{{ selected_usc }}">
        </div>
        <details class="expander">
            <summary style="font-weight:400;">Or... upload a .usc file manually</summary>
            <input type="file" name="uploaded_file" accept=".usc">
        </details>
        <div>
            <label for="start_measure">Start measure:</label>
            <input type="number" name="start_measure" id="start_measure" min="0" value="{{ start_measure }}">
        </div>
        <div>
            <label for="end_measure">End measure:</label>
            <input type="number" name="end_measure" id="end_measure" min="{{ start_measure }}" value="{{ end_measure }}">
        </div>
        <button type="submit" name="clip_chart">Clip Chart</button>
    </form>
    {% if sekai_link %}
        <div style="margin-top:1.5em;text-align:center;">
            <a href="{{ sekai_link }}" target="_blank" style="color:var(--primary);font-weight:600;text-decoration:underline;">Download song jacket and music file from sekai.best</a>
        </div>
    {% endif %}
    {% if download_link %}
        <div class="download-link">
            <a href="{{ download_link }}">Download {{ out_name }}</a>
        </div>
    {% endif %}
    {% if error %}
        <div class="error">{{ error }}</div>
    {% endif %}
</div>
<script>
const uscFiles = {{ usc_files|tojson }};
const uscSearch = document.getElementById('usc_search');
const uscDropdown = document.getElementById('usc_dropdown');
const selectedUscInput = document.getElementById('selected_usc');
const startMeasureInput = document.getElementById('start_measure');
const endMeasureInput = document.getElementById('end_measure');

function showDropdown(filtered) {
    uscDropdown.innerHTML = "";
    if (filtered.length === 0) {
        uscDropdown.classList.remove('visible');
        return;
    }
    filtered.forEach(function(file) {
        const div = document.createElement('div');
        div.className = 'usc-option';
        div.textContent = file;
        div.onclick = function() {
            uscSearch.value = file;
            selectedUscInput.value = file;
            uscDropdown.classList.remove('visible');
        };
        uscDropdown.appendChild(div);
    });
    uscDropdown.classList.add('visible');
}

uscSearch.addEventListener('input', function() {
    const filter = uscSearch.value.toLowerCase();
    const filtered = uscFiles.filter(f => f.toLowerCase().includes(filter));
    showDropdown(filtered);
});

uscSearch.addEventListener('focus', function() {
    const filter = uscSearch.value.toLowerCase();
    const filtered = uscFiles.filter(f => f.toLowerCase().includes(filter));
    showDropdown(filtered);
});

document.addEventListener('click', function(e) {
    if (!uscDropdown.contains(e.target) && e.target !== uscSearch) {
        uscDropdown.classList.remove('visible');
    }
});
endMeasureInput.addEventListener('blur', function() {
    let startVal = parseInt(startMeasureInput.value) || 0;
    let endVal = parseInt(endMeasureInput.value) || 0;
    if (endVal < startVal) {
        endMeasureInput.value = startVal + 1;
    }
});

startMeasureInput.addEventListener('blur', function() {
    let startVal = parseInt(startMeasureInput.value) || 0;
    let endVal = parseInt(endMeasureInput.value) || 0;
    if (endVal < startVal) {
        endMeasureInput.value = startVal + 1;
    }
});
</script>
</body>
</html>
"""

@app.route("/", methods=["GET", "POST"])
def index():
    usc_folder = os.path.join(os.path.dirname(__file__), "official_charts_usc")
    usc_files = []
    if os.path.exists(usc_folder):
        usc_files = [f for f in os.listdir(usc_folder) if f.lower().endswith(".usc")]

    selected_usc = request.form.get("selected_usc", "(None)")
    start_measure = int(request.form.get("start_measure", 0))
    end_measure = int(request.form.get("end_measure", max(1, start_measure + 1)))
    file_content = None
    filename = None
    sekai_link = None
    download_link = None
    out_name = None
    error = None

    if request.method == "POST":
        uploaded_file = request.files.get("uploaded_file")
        if uploaded_file and uploaded_file.filename:
            file_content = uploaded_file.read()
            filename = uploaded_file.filename
        elif selected_usc and selected_usc != "(None)":
            try:
                with open(os.path.join(usc_folder, selected_usc), "rb") as f:
                    file_content = f.read()
                filename = selected_usc
                song_id = filename.split('_')[0]
                sekai_link = f"https://sekai.best/music/{song_id}"
            except Exception as e:
                error = f"Error loading file: {e}"

        if file_content is not None and "clip_chart" in request.form:
            try:
                clipped_json = process_chart(file_content, start_measure, end_measure)
                out_name = f"clipped_{filename}" if filename else "clipped.usc"
                # Save to a temp file for download
                temp_path = os.path.join("temp", out_name)
                os.makedirs("temp", exist_ok=True)
                with open(temp_path, "w", encoding="utf-8") as f:
                    f.write(clipped_json)
                download_link = url_for("download_file", filename=out_name)
            except Exception as e:
                error = f"Error processing chart: {e}"

    return render_template_string(
        HTML_TEMPLATE,
        version_number=version_number,
        usc_files=usc_files,
        selected_usc=selected_usc,
        start_measure=start_measure,
        end_measure=end_measure,
        sekai_link=sekai_link,
        download_link=download_link,
        out_name=out_name,
        error=error
    )

@app.route("/download/<filename>")
def download_file(filename):
    return send_from_directory("temp", filename, as_attachment=True)

if __name__ == "__main__":
    app.run(debug=True)
