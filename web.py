import streamlit as st

import config
import utils
from component_manager import ComponentManager


utils.initialize()

st.set_page_config(page_title="Cynia Agents", page_icon="🧩")

manager = ComponentManager()


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
        
        # 在卡片渲染后立即添加toggle，让它看起来在卡片内部
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


def build_pages():
    pages = {"Component Center": None}
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