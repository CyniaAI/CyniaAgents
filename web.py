import streamlit as st

import config
import utils
from component_manager import ComponentManager


utils.initialize()

st.set_page_config(page_title="Cynia Agents", page_icon="🧩")

st.title("Cynia Agents UI")

manager = ComponentManager()


def render_component_center():
    """UI for enabling/disabling components."""
    st.header("Component Center")
    for name, comp in manager.available.items():
        enabled = name in manager.enabled
        label = f"{name}"
        if comp.description:
            label += f" - {comp.description}"
        checked = st.checkbox(label, value=enabled)
        if checked and name not in manager.enabled:
            manager.enabled.append(name)
        if not checked and name in manager.enabled:
            manager.enabled.remove(name)

    if st.button("Save configuration"):
        manager.save_config()
        st.success("Configuration saved")


def build_pages():
    pages = {"Component Center": None}
    for comp in manager.get_enabled_components():
        pages[comp.name] = comp
    return pages


pages = build_pages()
selected = st.sidebar.radio("Pages", list(pages.keys()))

if selected == "Component Center":
    render_component_center()
else:
    component = pages[selected]
    component.render()
