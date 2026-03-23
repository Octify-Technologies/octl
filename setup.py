from setuptools import setup

setup(
    name="octl",
    version="1.2.0",
    description="Octify dev workflow CLI",
    py_modules=["cli"],
    entry_points={
        "console_scripts": [
            "octl=cli:main",
            "syncenv=cli:syncenv_cmd",
            "clean-branches=cli:clean_branches_cmd",
        ],
    },
    python_requires=">=3.8",
)
