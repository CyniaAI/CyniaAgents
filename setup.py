from setuptools import setup, find_packages

setup(
    name="cynia-agents",
    version="2.0.0",
    packages=find_packages(),
    py_modules=[
        "cynia_cli",
        "web",
        "config",
        "utils",
        "component_manager",
        "artifact_manager",
        "ui_components",
        "component_base",
        "log_writer",
        "version_checker",
        "component_load_guard",
    ],
    include_package_data=True,
    install_requires=[
        "streamlit",
        "watchdog",
        "python-dotenv",
        "chardet",
        "requests",
        "psutil",
        "packaging",
        "langchain",
        "langchain-openai",
        "langchain-google-genai",
        "langchain-anthropic",
    ],
    entry_points={
        "console_scripts": [
            "cynia-agents=cynia_cli:main",
        ],
    },
    author="CyniaAgents Team",
    description="A lightweight framework for running generative agents through a Streamlit interface.",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.8',
)
