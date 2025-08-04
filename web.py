import streamlit as st
import os

import config
import utils
from component_manager import ComponentManager
import artifact_manager
from ui_components import DependencyInstallationUI, ZipImportUI, ComponentManagementUI, RealTimeStatusUI


utils.initialize()

st.set_page_config(page_title="Cynia Agents", page_icon="🧩")

manager = ComponentManager()

# Initialize UI components
dependency_ui = DependencyInstallationUI(manager)
zip_import_ui = ZipImportUI(manager)
component_mgmt_ui = ComponentManagementUI(manager)
status_ui = RealTimeStatusUI(manager)


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
    """Enhanced UI for component management with hot reload functionality."""
    st.header("🧩 Component Center")
    st.markdown("Manage your components with hot reload, dependency installation, and ZIP import capabilities.")
    
    # Create tabs for different functionalities
    tab1, tab2, tab3, tab4 = st.tabs(["📦 Components", "🔧 Dependencies", "📁 Import ZIP", "📊 Status"])
    
    with tab1:
        # Component management with enhanced controls
        st.subheader("Component Management")
        
        if not manager.available:
            st.info("No components found. Please add components to the components directory.")
            
            # Show ZIP import option when no components
            st.markdown("---")
            st.markdown("**Get started by importing a component:**")
            zip_import_ui.render_zip_import_interface()
            return
        
        # Render enhanced component cards
        for name, comp in manager.available.items():
            component_mgmt_ui.render_component_card(name, comp)
        
        # Save configuration section
        st.markdown("---")
        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            if st.button("💾 Save Configuration", type="primary"):
                manager.save_config()
                st.success("✅ Configuration saved successfully!")
                st.rerun()
    
    with tab2:
        # Dependency management interface
        st.subheader("Dependency Management")
        
        if not manager.available:
            st.info("No components available for dependency management.")
            return
        
        # Component selector for dependency management
        component_names = list(manager.available.keys())
        selected_component = st.selectbox(
            "Select component for dependency management:",
            component_names,
            key="dep_component_selector"
        )
        
        if selected_component:
            dependency_ui.render_dependency_installation_interface(selected_component)
    
    with tab3:
        # ZIP import interface
        zip_import_ui.render_zip_import_interface()
    
    with tab4:
        # Real-time status dashboard
        status_ui.render_status_dashboard()


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
