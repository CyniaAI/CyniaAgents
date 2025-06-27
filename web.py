import streamlit as st
import os

import config
import utils
from component_manager import ComponentManager
import artifact_manager


utils.initialize()

st.set_page_config(page_title="Cynia Agents", page_icon="🧩")

manager = ComponentManager()


def render_artifact_center():
    """UI for browsing generated artifacts."""
    st.header("📦 Artifact Center")
    artifacts = artifact_manager.list_artifacts()
    if not artifacts:
        st.info("No artifacts available.")
        return
    for art in artifacts:
        file_path = os.path.join(artifact_manager.ARTIFACTS_DIR, art["file"])
        cols = st.columns([3, 2, 1, 3, 1])
        cols[0].write(art["file"])
        cols[1].write(art.get("component", ""))
        cols[2].write(f"{art.get('size', 0)} bytes")
        cols[3].write(art.get("remark", ""))
        with open(file_path, "rb") as f:
            cols[4].download_button("Download", f.read(), file_name=art["file"])
        st.markdown("---")


def render_component_center():
    """UI for enabling/disabling components."""
    st.header("🧩 Component Center")
    st.markdown("Manage your components here. Enable or disable components as needed.")
    
    if not manager.available:
        st.info("No components found. Please add components to the components directory.")
        return
    
    # 检查是否有未保存的更改
    has_unsaved_changes = False
    current_enabled = []
    
    # 逐个显示组件卡片，每个卡片占满一行
    for name, comp in manager.available.items():
        original_enabled = name in manager.enabled
        
        # 先获取toggle状态来确定颜色
        toggle_key = f"toggle_{name}"
        if toggle_key in st.session_state:
            checked = st.session_state[toggle_key]
        else:
            checked = original_enabled
            
        # 根据当前toggle状态设置颜色
        if checked:
            title_color = "#ffffff"  # 启用时使用白色
            desc_color = "#ffffff"   # 启用时使用白色
            if name not in current_enabled:
                current_enabled.append(name)
        else:
            title_color = "#999999"  # 禁用时使用灰色
            desc_color = "#cccccc"   # 禁用时使用浅灰色
        
        # 渲染带有内嵌toggle的卡片
        st.markdown(f"""
            <div style="
                border-radius: 12px;
                padding: 20px;
                margin: 15px 0;
                background: transparent;
                box-shadow: 0 4px 8px rgba(0,0,0,0.1);
                transition: all 0.3s ease;
            ">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div style="flex: 1;">
                        <h3 style="margin: 0 0 8px 0; font-weight: 600; color: {title_color};">{name}</h3>
                        <p style="margin: 0; font-size: 14px; line-height: 1.5; color: {desc_color};">
                            {comp.description or 'No description available'}
                        </p>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)
        
        # 在卡片渲染后立即添加安装按钮和toggle，让它看起来在卡片内部
        col1, col2 = st.columns([6, 1])
        with col2:
            # 使用负的margin让toggle看起来在卡片内部
            st.markdown("""
                <style>
                .stToggle {
                    margin-top: -80px !important;
                    margin-right: 10px !important;
                }
                </style>
                """, unsafe_allow_html=True)

            checked = st.toggle(f"Enable", value=original_enabled, key=f"toggle_{name}")
            
            if checked and name not in current_enabled:
                current_enabled.append(name)
            
            # 检查是否有变化
            if checked != original_enabled:
                has_unsaved_changes = True

        with col1:
            missing = manager.missing_requirements(getattr(comp, "requirements", []))
            if missing:
                if st.button("Install requirements", key=f"install_{name}"):
                    with st.spinner("Installing..."):
                        success = manager.install_requirements(missing)
                    if success:
                        st.success("Requirements installed")
                    else:
                        st.error("Failed to install requirements")
                    st.rerun()
    
    # 显示未保存更改提示
    if has_unsaved_changes:
        st.warning("⚠️ You have unsaved changes. Please save configuration to apply changes.")
    
    # 保存配置按钮
    st.markdown("---")
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        if st.button("💾 Save Configuration", type="primary"):
            # 更新manager的enabled列表
            manager.enabled = current_enabled.copy()
            manager.save_config()
            st.success("✅ Configuration saved successfully!")
            # 自动刷新页面
            st.rerun()


def render_config_center():
    """UI for editing .env configuration values."""
    st.header("⚙️ Configuration Center")
    st.markdown("Edit configuration values stored in the `.env` file.")

    with st.form("config_form"):
        inputs = {}
        for key, meta in config.CONFIG_ITEMS.items():
            desc = meta.get("description", "")
            current = getattr(config, key, "")
            field_type = meta.get("type", "text")
            if field_type == "select":
                options = meta.get("options", [])
                if current in options:
                    index = options.index(current)
                else:
                    index = 0
                inputs[key] = st.selectbox(key, options, index=index, help=desc)
            elif field_type == "password":
                inputs[key] = st.text_input(key, value=current, help=desc, type="password")
            else:
                inputs[key] = st.text_input(key, value=current, help=desc)
        submitted = st.form_submit_button("Save")

    if submitted:
        for k, v in inputs.items():
            config.edit_config(k, v)
        st.success("Configuration saved successfully!")
        st.rerun()


def build_pages():
    pages = {
        "Component Center": None,
        "Configuration Center": None,
        "Artifact Center": None,
    }
    for comp in manager.get_enabled_components():
        pages[comp.name] = comp
    return pages


# 构建页面
pages = build_pages()

# 侧边栏导航
st.sidebar.title("🧩 Cynia Agents")
st.sidebar.markdown("---")

# 显示组件中心
if st.sidebar.button("🏠 Component Center", use_container_width=True):
    st.session_state.selected_page = "Component Center"

# 显示配置中心
if st.sidebar.button("⚙️ Configuration Center", use_container_width=True):
    st.session_state.selected_page = "Configuration Center"

# 显示Artifact中心
if st.sidebar.button("📦 Artifact Center", use_container_width=True):
    st.session_state.selected_page = "Artifact Center"

# 显示启用的组件
if manager.get_enabled_components():
    st.sidebar.markdown("### 📋 Enabled Components")
    for comp in manager.get_enabled_components():
        if st.sidebar.button(f"🔧 {comp.name}", use_container_width=True):
            st.session_state.selected_page = comp.name

# 初始化选中页面
if 'selected_page' not in st.session_state:
    st.session_state.selected_page = "Component Center"

# 显示侧边栏信息
st.sidebar.markdown("---")
st.sidebar.markdown("### 📊 Statistics")
st.sidebar.info(f"**Available Components:** {len(manager.available)}")
st.sidebar.info(f"**Enabled Components:** {len(manager.get_enabled_components())}")

# 渲染选中的页面
st.title("Cynia Agents UI")

if st.session_state.selected_page == "Component Center":
    render_component_center()
elif st.session_state.selected_page == "Configuration Center":
    render_config_center()
elif st.session_state.selected_page == "Artifact Center":
    render_artifact_center()
else:
    component = pages.get(st.session_state.selected_page)
    if component:
        st.header(f"🔧 {component.name}")
        if component.description:
            st.markdown(f"*{component.description}*")
        st.markdown("---")
        component.render()
    else:
        st.error("Component not found or not enabled.")
