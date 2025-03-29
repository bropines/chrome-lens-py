from setuptools import setup, find_packages
import pathlib

# The directory containing this file
HERE = pathlib.Path(__file__).parent

# The text of the README file
README = (HERE / "README.md").read_text(encoding="utf-8")

setup(
    name='chrome_lens_py',
    version='2.1.0',
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires='>=3.8',
    install_requires=[
        'requests',
        'Pillow',
        'filetype',
        'lxml',
        'json5',
        'rich',
        'PySocks',
        'httpx[http2]',
        'socksio',
        'numpy',
    ],
    entry_points={
        'console_scripts': [
            'lens_scan=chrome_lens_py.main:cli_run', # Указываем cli_run как entry point
        ],
    },
    description='Library to use Google Lens OCR for free via API used in Chromium on python ',
    long_description=README,
    long_description_content_type='text/markdown',  # Указание типа содержимого
    author='Bropines',
    author_email='bropines@gmail.com',
    url='https://github.com/bropines/chrome-lens-py',
    classifiers=[
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
)
