from setuptools import setup

setup(
    name="octl",
    version="1.0.0",
    description="Octify dev workflow CLI",
    py_modules=["octl_cli"],
    entry_points={
        "console_scripts": [
            "octl=octl_cli:main",
            "clean-branches=octl_cli:clean_branches_cmd",
        ],
    },
    python_requires=">=3.8",
)