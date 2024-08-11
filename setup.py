from setuptools import setup, find_packages

setup(
    name='chrome_lens_py',
    version='1.0.0',
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    install_requires=[
        'requests',
        'Pillow',
        'filetype',
        'lxml',
        'json5',
        'rich',
    ],
    entry_points={
        'console_scripts': [
            'lens_scan=chrome_lens_py.main:main',
        ],
    },
    description='Library to use Google Lens OCR for free, via API used in Chromium.',
    author='Bropines',
    author_email='bropines@gmail.com',
    url='https://github.com/bropines/chrome-lens-api-py',
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
)
