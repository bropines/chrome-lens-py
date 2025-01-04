LENS_ENDPOINT = 'https://lens.google.com/v3/upload'
LENS_API_ENDPOINT = 'https://lens.google.com/uploadbyurl'

SUPPORTED_MIMES = [
    'image/x-icon',
    'image/bmp',
    'image/jpeg',
    'image/png',
    'image/tiff',
    'image/webp',
    'image/heic',
    'image/gif'
]

MIME_TO_EXT = {
    'image/x-icon': 'ico',
    'image/bmp': 'bmp',
    'image/jpeg': 'jpg',
    'image/png': 'png',
    'image/tiff': 'tiff',
    'image/webp': 'webp',
    'image/heic': 'heic',
    'image/gif': 'gif'
}

# HEADERS_OLD = {
#     'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
#     'Accept-Encoding': 'gzip, deflate, br',
#     'Accept-Language': 'en-US,en;q=0.9',
#     'Cache-Control': 'max-age=0',
#     'Origin': 'https://lens.google.com',
#     'Referer': 'https://lens.google.com/',
#     'Sec-Ch-Ua': '"Not A(Brand";v="99", "Google Chrome";v="131", "Chromium";v="131"',
#     'Sec-Ch-Ua-Arch': '"x86"',
#     'Sec-Ch-Ua-Bitness': '"64"',
#     'Sec-Ch-Ua-Full-Version': '"131.0.6778.205"',
#     'Sec-Ch-Ua-Full-Version-List': '"Not A(Brand";v="99.0.0.0", "Google Chrome";v="131", "Chromium";v="131"',
#     'Sec-Ch-Ua-Mobile': '?0',
#     'Sec-Ch-Ua-Platform': '"Windows"',
#     'Sec-Ch-Ua-Platform-Version': '"15.0.0"',
#     'Sec-Fetch-Dest': 'document',
#     'Sec-Fetch-Mode': 'navigate',
#     'Sec-Fetch-Site': 'same-origin',
#     'Sec-Fetch-User': '?1',
#     'Upgrade-Insecure-Requests': '1',
#     'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
# }

HEADERS_DEFAULT = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Accept-Language': 'en-US,en;q=0.9',
    'Cache-Control': 'max-age=0',
    'Origin': 'https://lens.google.com',
    'Referer': 'https://lens.google.com/',
    'User-Agent': 'Mozilla/5.0 (SMART-TV; Linux; Tizen 6.0) AppleWebKit/538.1 (KHTML, like Gecko) Version/6.0 TV Safari/538.1 STvPlus/9e6462f14a056031e5b32ece2af7c3ca,gzip(gfe),gzip(gfe)',
}

HEADERS_CUSTOM = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Accept-Language': 'en-US,en;q=0.9',
    'Cache-Control': 'max-age=0',
    'Origin': 'https://lens.google.com',
    'Referer': 'https://lens.google.com/',
    'Sec-Ch-Ua': '"Chromium";v="131", "Not A(Brand";v="99"',
    'Sec-Ch-Ua-Arch': '"arm"',
    'Sec-Ch-Ua-Bitness': '"64"',
    'Sec-Ch-Ua-Full-Version': '"131.0.6778.205"',
    'Sec-Ch-Ua-Full-Version-List': '"Chromium";v="131.0.6778.205", "Not A(Brand";v="99.0.0.0"',
    'Sec-Ch-Ua-Mobile': '?1',
    'Sec-Ch-Ua-Model': '"Pixel 7 Pro"',
    'Sec-Ch-Ua-Platform': '"Android"',
    'Sec-Ch-Ua-Platform-Version': '"13.0.0"',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'same-origin',
    'Sec-Fetch-User': '?1',
    'Upgrade-Insecure-Requests': '1',
    'User-Agent': 'Mozilla/5.0 (Linux; Android 13; Pixel 7 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36',
}
