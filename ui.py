from cube_qgui.__init__ import CreateQGUI
from cube_qgui.banner_tools import *
from cube_qgui.notebook_tools import *
import os

from log_writer import logger
import config
import core


# ---------- Functions ----------#
def open_config(args: dict) -> bool:
    """
    Opens the config file.

    Args:
        args (dict): A dictionary containing the necessary arguments.

    Returns:
        bool: Always True.
    """
    os.system("notepad .env")

    return True


def save_apply_config(args: dict) -> bool:
    """
    Saves and applies the configuration.

    Args:
        args (dict): A dictionary containing the necessary arguments.

    Returns:
        bool: Always True.
    """
    keys = ["API_KEY", "BASE_URL"]

    for key in keys:
        value = args[key].get()

        if key == "ADVANCED_MODE":
            value = True if value == 1 else False
        else:
            pass

        config.edit_config(key, value)

    config.load_config()

    args["DevTool_CONFIG_API_KEY_DISPLAY"].set(f"CONFIG.API_KEY = {config.API_KEY}")
    args["DevTools_CONFIG_BASE_URL_DISPLAY"].set(f"CONFIG.BASE_URL = {config.BASE_URL}")

    return True


def load_config(args: dict) -> bool:
    """
    Loads the configuration.

    Args:
        args (dict): A dictionary containing the necessary arguments.

    Returns:
        bool: Always True.
    """
    config.load_config()

    args["API_KEY"].set(config.API_KEY)
    args["BASE_URL"].set(config.BASE_URL)

    return True


def print_args(args: dict) -> bool:
    """
    Prints the arguments.

    Args:
        args (dict): A dictionary containing the arguments.

    Returns:
        bool: Always True.
    """
    for arg, v_fun in args.items():
        print(f"Name: {arg}, Value: {v_fun.get()}")

    return True


def raise_error(args: dict):
    """
    Raises an error.

    Args:
        args (dict): A dictionary containing the arguments.
    """
    raise Exception("This is a test error.")






# ---------- Main Program ----------#

root = CreateQGUI(title="BukkitGPT-v3",
                  tab_names=["Generate", "Edit", "Settings", "DevTools"]
                  )
error_msg = None

logger("Starting program.")

# Initialize Core
core.initialize()

print("BukkitGPT v3 beta console running")

# Banner
root.add_banner_tool(GitHub("https://github.com/CyniaAI/BukkitGPT-v3"))

# Generate Page
root.add_notebook_tool(
    InputBox(name="PluginName", default="ExamplePlugin", label_info="Plugin Name")
)
root.add_notebook_tool(
    InputBox(
        name="PluginDescription",
        default="Send msg 'hello' to every joined player.",
        label_info="Plugin Description",
    )
)

root.add_notebook_tool(
    RunButton(
        bind_func=core.generate,
        name="Generate",
        text="Generate Plugin",
        checked_text="Generating...",
        tab_index=0,
    )
)

# Edit Page #
root.add_notebook_tool(
    ChooseFileTextButton(
        name="OriginalJAR",
        label_info="Original JAR",
        tab_index=1
    )
)

root.add_notebook_tool(
    InputBox(
        name="EditRequest",
        default="Add a command to send a message to all players.",
        label_info="Edit Request",
        tab_index=1
    )
)

root.add_notebook_tool(
    RunButton(
        bind_func=core.edit,
        name="Edit",
        text="Edit Plugin",
        checked_text="Editing...",
        tab_index=1
    )
)

# Settings Page
root.add_notebook_tool(
    InputBox(
        name="API_KEY", 
        default=config.API_KEY, 
        label_info="API Key", 
        tab_index=2
    )
)
root.add_notebook_tool(
    InputBox(
        name="BASE_URL", 
        default=config.BASE_URL, 
        label_info="BASE URL", 
        tab_index=2
    )
)

config_buttons = HorizontalToolsCombine(
    [
        BaseButton(
            bind_func=save_apply_config,
            name="Save & Apply Config",
            text="Save & Apply",
            tab_index=2
        ),
        BaseButton(
            bind_func=load_config, 
            name="Load Config", 
            text="Load Config", 
            tab_index=2
        ),
        BaseButton(
            bind_func=open_config,
            name="Open Config",
            text="Open Full Config",
            tab_index=2
        ),
    ]
)
root.add_notebook_tool(config_buttons)

# DevTools Page
root.add_notebook_tool(
    Label(
        name="DevTool_DESCRIPTION",
        text="This is a testing page for developers. Ignore it if you are a normal user.",
        tab_index=3
    )
)
root.add_notebook_tool(
    Label(
        name="DevTool_CONFIG_API_KEY_DISPLAY",
        text=f"CONFIG.API_KEY = {config.API_KEY}",
        tab_index=3
    )
)
root.add_notebook_tool(
    Label(
        name="DevTools_CONFIG_BASE_URL_DISPLAY",
        text=f"CONFIG.BASE_URL = {config.BASE_URL}",
        tab_index=3
    )
)
root.add_notebook_tool(
    RunButton(
        bind_func=print_args, name="Print Args", text="Print Args", tab_index=3
    )
)
root.add_notebook_tool(
    RunButton(
        bind_func=raise_error, name="Raise Error", text="Raise Error", tab_index=3
    )
)

# Sidebar
root.set_navigation_about(
    author="CyniaAI Team",
    version=config.VERSION_NUMBER,
    github_url="https://github.com/CyniaAI/BukkitGPT-v3",
)


# Run
root.run()
