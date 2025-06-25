import os
import uuid
import shutil
import queue
from pathlib import Path

import build
import config
import utils
from log_writer import logger

# Re-export utility functions for backward compatibility
initialize = utils.initialize
askgpt = utils.askgpt
response_to_action = utils.response_to_action
mixed_decode = utils.mixed_decode
decompile_jar = utils.decompile_jar
code_to_text = utils.code_to_text
parse_edit_response = utils.parse_edit_response
apply_diff_changes = utils.apply_diff_changes


def generate(args: dict, output_queue: queue.Queue = None) -> bool:
    """Generate a new plugin using the provided arguments."""
    name = args["PluginName"].get()
    description = args["PluginDescription"].get()

    artifact_name = name.replace(" ", "")
    package_id = f"dev.cynia.{uuid.uuid4().hex[:8]}"
    pkg_id_path = "".join(id + "/" for id in package_id.split("."))

    logger(f"user_input -> name: {name}")
    logger(f"user_input -> description: {description}")
    logger(f"random_generate -> package_id: {package_id}")
    logger(f"str_path -> pkg_id_path: {pkg_id_path}")

    if output_queue:
        output_queue.put("Generating plugin...")
    else:
        print("Generating plugin...")

    codes = askgpt(
        config.SYS_GEN.replace("%ARTIFACT_NAME%", artifact_name).replace(
            "%PKG_ID_LST%", pkg_id_path
        ),
        config.USR_GEN.replace("%DESCRIPTION", description),
        config.GENERATION_MODEL,
    )
    logger(f"codes: {codes}")

    response_to_action(codes)

    # 发送代码生成完成状态
    if output_queue:
        output_queue.put("STATUS:code_generated")
        output_queue.put("Code generated. Building now...")
    else:
        print("Code generated. Building now...")

    result = build.build_plugin(artifact_name, output_queue=output_queue)

    target_dir = f"codes/{artifact_name}/target"
    jar_files = [f for f in os.listdir(target_dir) if f.endswith('.jar')]

    if jar_files:
        # 发送构建完成状态
        if output_queue:
            output_queue.put("STATUS:build_complete")
        message = f"Build complete. Find your plugin at '{target_dir}/{jar_files[0]}'"
        if output_queue:
            output_queue.put(message)
        else:
            print(message)
    else:
        if output_queue:
            output_queue.put("STATUS:build_failed")
        error_message = (
            "Build failed. This is because the code LLM generated has syntax errors. "
            "Please try again or switch to a better LLM like o1 or r1. IT IS NOT A BUG OF BUKKITGPT."
        )
        if output_queue:
            output_queue.put(error_message)
        else:
            print(error_message)

    return True


def edit(args: dict, output_queue: queue.Queue = None) -> bool:
    """Edit an existing plugin according to the user's request."""
    original_jar = args["OriginalJAR"].get()
    edit_request = args["EditRequest"].get()

    jar_path = Path(original_jar)
    jar_name = jar_path.stem
    
    if jar_name.startswith('tmp') or 'temp' in jar_name.lower():
        jar_name = f"edited_plugin_{uuid.uuid4().hex[:8]}"
    
    decompiled_path = Path("codes") / "decompiled" / jar_name
    
    decompiled_path_str = str(decompiled_path)

    if output_queue:
        output_queue.put("Decompiling JAR file...")
    else:
        print("Decompiling JAR file...")

    decompile_jar(original_jar, decompiled_path_str)
    
    # 发送反编译完成状态
    if output_queue:
        output_queue.put("STATUS:decompiled")

    os.makedirs(f"{decompiled_path_str}/src/main/java", exist_ok=True)

    summary_path = os.path.join(decompiled_path_str, "summary.txt")
    if os.path.exists(summary_path):
        os.remove(summary_path)

    for item in os.listdir(decompiled_path_str):
        if item != 'src':
            s = os.path.join(decompiled_path_str, item)
            d = os.path.join(decompiled_path_str, "src/main/java", item)
            if os.path.isdir(s):
                shutil.move(s, d)
            elif os.path.isfile(s):
                shutil.move(s, d)

    with open(f"{decompiled_path_str}/pom.xml", "w") as f:
        f.write("<!-- Replace with the pom.xml code -->")

    if output_queue:
        output_queue.put("Analyzing code and generating edits...")
    else:
        print("Analyzing code and generating edits...")

    code_text = code_to_text(decompiled_path_str)
    response = askgpt(
        config.SYS_EDIT,
        config.USR_EDIT.replace("ORIGINAL_CODE", code_text).replace("REQUEST", edit_request),
        config.GENERATION_MODEL,
    )

    diffs = parse_edit_response(response)
    logger(f"[DEBUG] Extracted diffs: {diffs}")

    if output_queue:
        output_queue.put("Applying edits to source code...")
    else:
        print("Applying edits to source code...")

    resp = apply_diff_changes(diffs, decompiled_path_str)
    
    # 发送编辑应用完成状态
    if output_queue:
        output_queue.put("STATUS:edits_applied")

    if resp[0] is False:
        if output_queue:
            output_queue.put("STATUS:edit_failed")
        error_message = (
            "The diff LLM generated is invalid. Please try again or switch to a better LLM like o1 or r1. IT IS NOT A BUG OF BUKKITGPT."
        )
        if output_queue:
            output_queue.put(error_message)
        else:
            print(error_message)
        return False
    else:
        if output_queue:
            output_queue.put("Edits applied successfully. Starting rebuild...")
        else:
            print("Edits applied successfully. Starting rebuild...")
            
        result = build.build_plugin(decompiled_path_str, path=True, output_queue=output_queue)
        target_dir = f"{decompiled_path_str}/target"
        jar_files = [f for f in os.listdir(target_dir) if f.endswith('.jar')]

        if jar_files:
            # 发送重建完成状态
            if output_queue:
                output_queue.put("STATUS:rebuild_complete")
            message = f"Build complete. Find your plugin at '{target_dir}/{jar_files[0]}'"
            if output_queue:
                output_queue.put(message)
            else:
                print(message)
            return True
        else:
            if output_queue:
                output_queue.put("STATUS:rebuild_failed")
            error_message = (
                "Build failed. This is because the code LLM generated has syntax errors. "
                "Please try again or switch to a better LLM like o1 or r1. IT IS NOT A BUG OF BUKKITGPT."
            )
            if output_queue:
                output_queue.put(error_message)
            else:
                print(error_message)
            return False

