from setuptools import setup

setup(
	name="dope",
	version="1.0",
	py_modules=["dope"],
	install_requires=[
		"colorama",
		"GitPython",
		"pyaml",
		"wget",
	],
	entry_points={
		"console_scripts": [
			"dope = dope:main",
		],
	},
)