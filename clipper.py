import numpy as np
import pandas as pd
import json

def main(path, start_measure, end_measure, out_path):
    start_measure = start_measure
    end_measure = end_measure
    path = path
    start_beat = float(start_measure * 4)
    end_beat = float(end_measure * 4)

    def usc_to_string(path):
        with open(path) as f:
            base_usc = f.read()
        return base_usc

    string_usc = usc_to_string(path)
    usc_json = json.loads(string_usc)
    objects = usc_json["usc"]["objects"]

    # utilities
    def return_type(event, type):
        return event["type"] == type

    def trimmer(object):
        if object["beat"] < start_beat or object["beat"] > end_beat:
            return False # False = object gets trimmed out of .usc
        else:
            return True # True = object stays in .usc
        
    def trimmer_only_start(object):
        if object["beat"] < start_beat:
            return False # False = object gets trimmed out of .usc
        else:
            return True # True = object stays in .usc
        
    def trimmer_only_end(object):
        if object["beat"] > end_beat:
            return False # False = object gets trimmed out of .usc
        else:
            return True # True = object stays in .usc 

    def shifter(object):
        new_beat = object["beat"] - start_beat
        return {
            **object,
            "beat": new_beat
        }

    bpm_objects = [x for x in objects if return_type(x, "bpm")]


    # offset finding
    # note that for start_measure = 0, offset can just be set to 0
    # offset is stored in seconds under variable offset_seconds
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
    for s in shifted_bpm_objects:
        print(s)

    for i in range(len(offset_finding_table["beat"].to_list())):
        if offset_finding_table.at[i, "beat"] < start_beat:
            offset_seconds += ((offset_finding_table.at[i+1, "beat"] - offset_finding_table.at[i, "beat"]) / offset_finding_table.at[i, "bpm"]) * 60
        elif offset_finding_table.at[i, "beat"] >= start_beat:
            break

    print("offset for chart clip: " + f"{offset_seconds}")

    def add_default_to_timeScaleGroup_if_needed(speed_object):
        # check if there's already a speed change at 0, if so dont do anything
        for change in speed_object["changes"]:
            if change["beat"] == 0:
                return speed_object
        # if we got here, there is no speed event at 0, so must create one whilst keeping the other possible speed changes
        new_changes = [{'beat': 0.0, 'timeScale': 1.0}]
        new_changes.extend(speed_object["changes"])
        return {
            **speed_object,
            "changes": new_changes
        }

    # find initial speeds for all timeScaleGroups that exist
    speed_objects = [add_default_to_timeScaleGroup_if_needed(x) for x in objects if return_type(x, "timeScaleGroup")]
    print(speed_objects[0])
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

    # print(new_speed_object(speed_objects[0], trimmed_shifted_speed_changes[0]))
    trimmed_shifted_speed_objects = []
    for k in range(len(speed_objects)):
        trimmed_shifted_speed_objects.append(new_speed_object(speed_objects[k], trimmed_shifted_speed_changes[k]))

    for s in trimmed_shifted_speed_objects:
        print(s)

    # process all notes with type="single" (regular notes, flicks, gold notes, traces)
    single_objects = [x for x in objects if return_type(x, "single")]

    shifted_single_objects = [shifter(x) for x in single_objects if trimmer(x)]
    for s in shifted_single_objects:
        print(s)
            
    guide_objects = [x for x in objects if return_type(x, "guide")]

    def trim_guide(guide_object):
        for midpoint in guide_object["midpoints"]:
            if trimmer(midpoint) == False:
                return False
        return True

    # guide_objects is a list of guide objects
    # guide objects are made up of midpoints
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

    shifted_guide_objects = [guide_trimmer_and_shifter(x) for x in guide_objects if trim_guide(x)]
    for s in shifted_guide_objects:
        print(s)

    slide_objects = [x for x in objects if return_type(x, "slide")]

    def check_slide(slide_object):
        slide_midpoints = slide_object["connections"]
        # if ANY point is BEFORE the trim, DO NOT permit the slide.
        for midpoint in slide_midpoints:
            if trimmer_only_start(midpoint) == False:
                return False
        # if ALL points are AFTER the trim, DO NOT permit the slide.
        for midpoint in slide_midpoints:
            if trimmer_only_end(midpoint):
                # i.e. if ANY point is BEFORE the end point, DO allow the slide.
                return True
        # hence we reach here if ALL points fail trimmer_only_end, i.e. they are all AFTER the end point.
        # +50 picarats
        return False

    def shift_slide(slide_object):
        slide_midpoints = slide_object["connections"]
        end_midpoint = None
        for midpoint in slide_midpoints:
            if midpoint['type'] == 'end':
                end_midpoint = midpoint
        
        if end_midpoint is None:
            raise Exception("Slide did not contain an ending, this should never happen")
        # if the end midpoint is past the end of the trim,
        # cap it to the trim and change the judgetype to "none" (which makes it a invisible ending like Heat Abnormal, for instance)
        should_cap_ending = end_midpoint["beat"] > end_beat
        adjusted_midpoints = []
        all_midpoints_except_end = [x for x in slide_midpoints if x['type'] != 'end']
        for midpoint in all_midpoints_except_end:
            new_midpoint = shifter(midpoint)
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
            adjusted_midpoints.append(shifter(end_midpoint))
        return {
            **slide_object,
            "connections": adjusted_midpoints
        }


    trimmed_shifted_slide_objects = [shift_slide(x) for x in slide_objects if check_slide(x)]
    for s in trimmed_shifted_slide_objects:
        print(s)

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

    with open(out_path, "w") as f:
        s = json.dumps(final_obj)
        f.write(s)

if __name__ == "__main__":
    import sys
    input_file_name = sys.argv[1]
    start_measure = int(sys.argv[2])
    end_measure = int(sys.argv[3])
    out_path = sys.argv[4]
    main(input_file_name, start_measure, end_measure, out_path)