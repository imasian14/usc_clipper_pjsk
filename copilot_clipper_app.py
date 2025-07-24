import numpy as np
import pandas as pd
import json
import io
import os
import base64
import streamlit as st

version_number = 1.2

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

# --- Streamlit Web UI ---
st.title("Chart Clipper")

st.write("Tutorial to use this website: https://docs.google.com/document/d/e/2PACX-1vQ_o-nqbWOHlKQJiOhtowcCdvFFNptK1ngGnW85YK-ZKCbfaLR9b4lrdVKQdLfcmzJV_WGtx8uK83tX/pub")
st.write("Select an existing chart, select start and end measures, and download the clipped chart. Alternatively, upload your own .usc file.")
st.write("Please ping @imasian. on discord if chart is not available.")
st.write(f"Version: {version_number}")

# List .usc files in the 'uscs' folder (relative to this script)
usc_folder = os.path.join(os.path.dirname(__file__), "official_charts_usc")
usc_files = []
if os.path.exists(usc_folder):
    usc_files = [f for f in os.listdir(usc_folder) if f.lower().endswith(".usc")]

selected_usc = None

if usc_files:
    selected_usc = st.selectbox(
        "Select a chart here (searchable):",
        ["(None)"] + usc_files,
        index=0,
        placeholder="Type to search..."
    )

with st.expander("Or... Upload a .usc file manually"):
    uploaded_file = st.file_uploader("Drag and drop your .usc file here", type=["usc"])



start_measure = st.number_input("Start measure", min_value=0, value=0)
end_measure = st.number_input("End measure", min_value=start_measure, value=max(1, start_measure + 1))

file_content = None
filename = None

if uploaded_file is not None:
    file_content = uploaded_file.read()
    filename = uploaded_file.name
elif selected_usc and selected_usc != "(None)":
    with open(os.path.join(usc_folder, selected_usc), "rb") as f:
        file_content = f.read()
    filename = selected_usc
    song_id = filename.split('_')[0]
    st.markdown(f"[Click here to download song jacket and music file from sekai.best](https://sekai.best/music/{song_id})")

if file_content is not None:
    if st.button("Clip Chart"):
        clipped_json = process_chart(file_content, start_measure, end_measure)
        b64 = base64.b64encode(clipped_json.encode()).decode()
        out_name = f"clipped_{filename}" if filename else "clipped.usc"
        href = f'<a href="data:application/json;base64,{b64}" download="{out_name}">Download {out_name}</a>'
        st.markdown(href, unsafe_allow_html=True)

# To run streamlit locally: streamlit run .\copilot_clipper_app.py