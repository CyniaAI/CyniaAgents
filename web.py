import streamlit as st
import tempfile
import os
import threading
import queue
import time
import zipfile
import shutil
from pathlib import Path

import core
import config

class Arg:
    def __init__(self, value: str):
        self.value = value
    def get(self):
        return self.value

core.initialize()

st.set_page_config(page_title="BukkitGPT v3", page_icon="🧩")

st.title("BukkitGPT v3 WebUI")

tab_generate, tab_edit, tab_downloads, tab_settings = st.tabs(["Generate", "Edit", "Downloads", "Settings"])

# 初始化session state
if 'last_generate_args' not in st.session_state:
    st.session_state.last_generate_args = None
if 'last_edit_args' not in st.session_state:
    st.session_state.last_edit_args = None
if 'generation_completed' not in st.session_state:
    st.session_state.generation_completed = False
if 'edit_completed' not in st.session_state:
    st.session_state.edit_completed = False

def find_generated_files(plugin_name):
    """查找生成的文件"""
    # 根据core.py中的逻辑，生成的文件在codes/{artifact_name}/target/目录下
    codes_dir = Path("codes")
    artifact_name = plugin_name.replace(" ", "")
    target_dir = codes_dir / artifact_name / "target"
    
    jar_files = []
    if target_dir.exists():
        jar_files = list(target_dir.glob("*.jar"))
    
    return jar_files, target_dir

def find_edited_files():
    """查找编辑后的文件"""
    # 根据core.py中的逻辑，编辑后的文件在codes/decompiled/{jar_name}/target/目录下
    decompiled_dir = Path("codes/decompiled")
    jar_files = []
    source_dirs = []
    
    if decompiled_dir.exists():
        for subdir in decompiled_dir.iterdir():
            if subdir.is_dir():
                target_dir = subdir / "target"
                if target_dir.exists():
                    jar_files.extend(list(target_dir.glob("*.jar")))
                    source_dirs.append(subdir)
    
    return jar_files, source_dirs

def find_all_projects():
    """查找所有项目文件"""
    all_projects = []
    
    # 查找生成的项目
    codes_dir = Path("codes")
    if codes_dir.exists():
        for subdir in codes_dir.iterdir():
            if subdir.is_dir() and subdir.name != "decompiled":
                target_dir = subdir / "target"
                if target_dir.exists():
                    jar_files = list(target_dir.glob("*.jar"))
                    if jar_files:
                        latest_jar = max(jar_files, key=os.path.getctime)
                        all_projects.append({
                            "name": subdir.name,
                            "type": "Generated",
                            "jar_path": latest_jar,
                            "project_dir": subdir,
                            "modified_time": os.path.getctime(latest_jar)
                        })
    
    # 查找编辑的项目
    decompiled_dir = Path("codes/decompiled")
    if decompiled_dir.exists():
        for subdir in decompiled_dir.iterdir():
            if subdir.is_dir():
                target_dir = subdir / "target"
                if target_dir.exists():
                    jar_files = list(target_dir.glob("*.jar"))
                    if jar_files:
                        latest_jar = max(jar_files, key=os.path.getctime)
                        all_projects.append({
                            "name": subdir.name,
                            "type": "Edited",
                            "jar_path": latest_jar,
                            "project_dir": subdir,
                            "modified_time": os.path.getctime(latest_jar)
                        })
    
    # 按修改时间排序（最新的在前面）
    all_projects.sort(key=lambda x: x["modified_time"], reverse=True)
    return all_projects

def create_download_zip(project_dir):
    """创建包含项目所有文件的ZIP包"""
    # 创建临时ZIP文件
    with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp_zip:
        with zipfile.ZipFile(tmp_zip.name, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # 添加整个项目文件夹
            for file_path in project_dir.rglob('*'):
                if file_path.is_file():
                    arcname = str(file_path.relative_to(project_dir.parent))
                    zipf.write(file_path, arcname)
        
        return tmp_zip.name

with tab_generate:
    plugin_name = st.text_input("Plugin Name", "ExamplePlugin")
    plugin_desc = st.text_area(
        "Plugin Description",
        "Send msg 'hello' to every joined player.",
    )

    col1, col2 = st.columns([1, 1])
    
    with col1:
        generate_button = st.button("Generate Plugin", type="primary")
    
    with col2:
        if st.session_state.last_generate_args and st.button("🔄 Regenerate"):
            # 使用上次的参数重新生成
            plugin_name = st.session_state.last_generate_args["PluginName"].get()
            plugin_desc = st.session_state.last_generate_args["PluginDescription"].get()
            generate_button = True

    if generate_button:
        # 重置完成状态
        st.session_state.generation_completed = False
        
        # 创建步骤显示区域
        step_container = st.container()
        with step_container:
            st.subheader("Generation Progress")
            step1 = st.empty()
            step2 = st.empty()
            output_container = st.empty()
        
        try:
            # 步骤1: 生成代码
            step1.info("🔄 Step 1: Generating code...")
            step2.empty()
            
            args = {
                "PluginName": Arg(plugin_name),
                "PluginDescription": Arg(plugin_desc),
            }
            
            # 保存参数到session state
            st.session_state.last_generate_args = args
            
            # 使用队列来捕获构建输出和状态
            build_output_queue = queue.Queue()
            status_queue = queue.Queue()
            
            def generate_with_output():
                try:
                    # 先生成代码
                    status_queue.put("code_generated")
                    core.generate(args, build_output_queue)
                    status_queue.put("build_complete")
                    return True
                except Exception as e:
                    build_output_queue.put(f"ERROR: {str(e)}")
                    status_queue.put("error")
                    return False
            
            # 在线程中运行生成
            thread = threading.Thread(target=generate_with_output)
            thread.start()
            
            # 实时显示输出和状态
            output_text = ""
            output_display = output_container.empty()
            code_generated = False
            
            while thread.is_alive() or not build_output_queue.empty():
                # 检查构建输出
                try:
                    line = build_output_queue.get_nowait()
                    # 检查是否是状态消息
                    if line.startswith("STATUS:"):
                        status = line.replace("STATUS:", "")
                        if status == "code_generated" and not code_generated:
                            step1.success("✅ Step 1: Code generation complete")
                            step2.info("🔄 Step 2: Building plugin...")
                            code_generated = True
                        elif status == "build_complete":
                            step2.success("✅ Step 2: Build complete")
                        elif status in ["build_failed", "error"]:
                            if code_generated:
                                step2.error("❌ Step 2: Build failed")
                            else:
                                step1.error("❌ Step 1: Code generation failed")
                            break
                    else:
                        # 普通输出消息
                        output_text += line + "\n"
                        with output_display.container():
                            st.text_area("Build Output:", value=output_text, height=300, disabled=True)
                except queue.Empty:
                    time.sleep(0.1)
            
            thread.join()
            
            if not code_generated:
                step1.error("❌ Step 1: Code generation failed")
            else:
                st.success("🎉 Generation complete!")
                st.info("📁 Please check the **Downloads** tab to download your generated plugin.")
                st.session_state.generation_completed = True
            
        except Exception as e:
            step1.error(f"❌ Step 1 failed: {str(e)}")
            step2.empty()
            st.error(str(e))
            st.session_state.generation_completed = False

with tab_edit:
    original_jar = st.file_uploader("Original JAR", type=['jar'], accept_multiple_files=False)
    edit_request = st.text_area(
        "Edit Request",
        "Add a command to send a message to all players.",
    )

    col1, col2 = st.columns([1, 1])
    
    with col1:
        edit_button = st.button("Edit Plugin", type="primary")
    
    with col2:
        if st.session_state.last_edit_args and st.button("🔄 Re-edit"):
            # 使用上次的参数重新编辑
            edit_request = st.session_state.last_edit_args["EditRequest"].get()
            edit_button = True

    if edit_button:
        if original_jar is None:
            st.error("Please select a JAR file first.")
        else:
            # 重置完成状态
            st.session_state.edit_completed = False
            
            # 创建步骤显示区域
            step_container = st.container()
            with step_container:
                st.subheader("Edit Progress")
                step1 = st.empty()
                step2 = st.empty()
                step3 = st.empty()
                output_container = st.empty()
            
            with tempfile.NamedTemporaryFile(delete=False, suffix='.jar') as tmp_file:
                tmp_file.write(original_jar.getvalue())
                jar_path = tmp_file.name
            
            # 步骤1: 反编译
            step1.info("🔄 Step 1: Decompiling JAR...")
            step2.empty()
            step3.empty()
            
            args = {
                "OriginalJAR": Arg(jar_path),
                "EditRequest": Arg(edit_request),
            }
            
            # 保存参数到session state
            st.session_state.last_edit_args = args
            
            # 使用队列来捕获构建输出和状态
            build_output_queue = queue.Queue()
            status_queue = queue.Queue()
            
            def edit_with_output():
                try:
                    result = core.edit(args, build_output_queue)
                    return result
                except Exception as e:
                    build_output_queue.put(f"ERROR: {str(e)}")
                    build_output_queue.put("STATUS:error")
                    return False
            
            # 在线程中运行编辑
            thread = threading.Thread(target=edit_with_output)
            thread.start()
            
            # 实时显示输出和状态
            output_text = ""
            output_display = output_container.empty()
            decompiled = False
            edits_applied = False
            rebuild_complete = False
            process_success = False
            
            while thread.is_alive() or not build_output_queue.empty():
                # 检查构建输出
                try:
                    line = build_output_queue.get_nowait()
                    # 检查是否是状态消息
                    if line.startswith("STATUS:"):
                        status = line.replace("STATUS:", "")
                        if status == "decompiled" and not decompiled:
                            step1.success("✅ Step 1: Decompilation complete")
                            step2.info("🔄 Step 2: Applying edits...")
                            decompiled = True
                        elif status == "edits_applied" and not edits_applied:
                            step2.success("✅ Step 2: Edits applied")
                            step3.info("🔄 Step 3: Rebuilding plugin...")
                            edits_applied = True
                        elif status == "rebuild_complete":
                            step3.success("✅ Step 3: Rebuild complete")
                            rebuild_complete = True
                            process_success = True
                        elif status == "edit_failed":
                            step2.error("❌ Step 2: Edit application failed")
                            break
                        elif status == "rebuild_failed":
                            step3.error("❌ Step 3: Rebuild failed")
                            break
                        elif status == "error":
                            if not decompiled:
                                step1.error("❌ Step 1: Decompilation failed")
                            elif not edits_applied:
                                step2.error("❌ Step 2: Edit application failed")
                            else:
                                step3.error("❌ Step 3: Rebuild failed")
                            break
                    else:
                        # 普通输出消息
                        output_text += line + "\n"
                        with output_display.container():
                            st.text_area("Build Output:", value=output_text, height=300, disabled=True)
                except queue.Empty:
                    time.sleep(0.1)
            
            thread.join()
            
            # Clean up temporary file
            os.unlink(jar_path)
            
            if rebuild_complete and process_success:
                st.success("🎉 Edit complete!")
                st.info("📁 Please check the **Downloads** tab to download your edited plugin.")
                st.session_state.edit_completed = True
            else:
                st.error("❌ Edit process failed")
                st.session_state.edit_completed = False
                
            # 清理临时文件
            try:
                if os.path.exists(jar_path):
                    os.unlink(jar_path)
            except Exception as e:
                st.warning(f"Warning cleaning up temporary files: {str(e)}")
            finally:
                # 反编译失败时，尝试删除生成的文件
                if not decompiled:
                    try:
                        artifact_name = os.path.basename(jar_path).replace(".jar", "")
                        target_dir = Path("codes") / artifact_name / "target"
                        if target_dir.exists():
                            shutil.rmtree(target_dir)
                    except Exception as e:
                        st.warning(f"Warning cleaning up generated files: {str(e)}")

with tab_downloads:
    st.subheader("📁 Download Center")
    st.write("Download all your generated and edited plugins from here.")
    
    # 获取所有项目
    all_projects = find_all_projects()
    
    if not all_projects:
        st.info("🔍 No plugins found. Generate or edit a plugin first!")
    else:
        st.write(f"Found **{len(all_projects)}** plugin(s):")
        
        for i, project in enumerate(all_projects):
            with st.expander(f"🧩 {project['name']} ({project['type']})", expanded=i==0):
                col1, col2, col3 = st.columns([2, 1, 1])
                
                with col1:
                    st.write(f"**Type:** {project['type']}")
                    st.write(f"**Location:** `{project['project_dir']}`")
                    modification_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(project['modified_time']))
                    st.write(f"**Modified:** {modification_time}")
                
                with col2:
                    # 下载JAR文件
                    if project['jar_path'].exists():
                        with open(project['jar_path'], "rb") as file:
                            jar_data = file.read()
                            jar_name = project['jar_path'].name
                            if project['type'] == "Edited":
                                jar_name = f"edited_{jar_name}"
                            
                            st.download_button(
                                label="📦 Download JAR",
                                data=jar_data,
                                file_name=jar_name,
                                mime="application/java-archive",
                                key=f"jar_{i}"
                            )
                    else:
                        st.error("JAR file not found")
                
                with col3:
                    # 下载项目ZIP
                    if project['project_dir'].exists():
                        zip_name = f"{project['name']}_project.zip"
                        if project['type'] == "Edited":
                            zip_name = f"edited_{zip_name}"
                        
                        # 创建ZIP并立即读取数据
                        zip_path = create_download_zip(project['project_dir'])
                        try:
                            with open(zip_path, "rb") as file:
                                zip_data = file.read()
                            
                            st.download_button(
                                label="📁 Download ZIP",
                                data=zip_data,
                                file_name=zip_name,
                                mime="application/zip",
                                key=f"zip_{i}"
                            )
                        except Exception as e:
                            st.error(f"Failed to create ZIP: {str(e)}")
                        finally:
                            # 安全地删除临时文件
                            try:
                                if os.path.exists(zip_path):
                                    os.unlink(zip_path)
                            except PermissionError:
                                # 如果无法删除，记录但不中断程序
                                pass
                    else:
                        st.error("Project folder not found")
        
        # 清理选项
        st.divider()
        if st.button("🗑️ Clear All Projects", type="secondary", help="This will delete all generated and edited projects"):
            if st.button("⚠️ Confirm Delete All", type="secondary"):
                try:
                    codes_dir = Path("codes")
                    if codes_dir.exists():
                        shutil.rmtree(codes_dir)
                    st.success("All projects have been deleted.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to delete projects: {str(e)}")

with tab_settings:
    st.write("Configuration")
    api_key = st.text_input("API Key", value=config.API_KEY, type="password")
    base_url = st.text_input("BASE URL", value=config.BASE_URL)

    if st.button("Save & Apply"):
        config.edit_config("API_KEY", api_key)
        config.edit_config("BASE_URL", base_url)
        config.load_config()
        st.success("Configuration saved and applied.")