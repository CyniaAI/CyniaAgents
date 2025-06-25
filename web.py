import streamlit as st

import config
import utils
from component_manager import ComponentManager


utils.initialize()

st.set_page_config(page_title="Cynia Agents", page_icon="🧩")

st.title("Cynia Agents UI")

manager = ComponentManager()

# Sidebar for component management
st.sidebar.header("Components")
for name, comp in manager.available.items():
    enabled = name in manager.enabled
    checked = st.sidebar.checkbox(f"{name}", value=enabled)
    if checked and name not in manager.enabled:
        manager.enabled.append(name)
    if not checked and name in manager.enabled:
        manager.enabled.remove(name)

if st.sidebar.button("Save configuration"):
    manager.save_config()
    st.sidebar.success("Configuration saved")

enabled_components = manager.get_enabled_components()

if not enabled_components:
    st.info("No components enabled. Enable them in the sidebar.")
else:
    comp_names = [c.name for c in enabled_components]
    selected = st.sidebar.selectbox("Active component", comp_names)
    component = next(c for c in enabled_components if c.name == selected)
    component.render()
