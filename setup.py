from cx_Freeze import setup, Executable

import config

files = [
    "logs",
    "codes",
    ".env",
    "LICENSE",
    "README.md",
    "requirements.txt",
    "banner.jpeg"
]

setup(name='BukkitGPT-v3',
      version=config.VERSION_NUMBER,
      maintainer="CyniaAI Team",
      maintainer_email="baimoqilin@gmail.com",
      url="https://github.com/CyniaAI/BukkitGPT-v3",
      license="Apache License 2.0",
      description='An open source, free, AI-powered Minecraft Bukkit plugin generator',
      executables=[Executable('ui.py', base="gui")],
      options={
          "build_exe": {
              "include_files": files,
          }
      })