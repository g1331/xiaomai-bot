import os
import requests


def ensure_directories():
    """
    创建存放静态资源的目录：static/css 与 static/js。
    """
    base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
    css_dir = os.path.join(base_dir, 'css')
    js_dir = os.path.join(base_dir, 'js')
    os.makedirs(css_dir, exist_ok=True)
    os.makedirs(js_dir, exist_ok=True)
    return css_dir, js_dir


def download_file(url: str, dest_path: str) -> None:
    """
    从指定 URL 下载文件，并保存到目标路径。

    Args:
        url (str): 文件的下载链接。
        dest_path (str): 文件保存的完整路径。
    """
    print(f"正在下载：{url}")
    response = requests.get(url)
    response.raise_for_status()  # 如果下载失败，则抛出异常
    with open(dest_path, 'wb') as f:
        f.write(response.content)
    print(f"文件已保存到：{dest_path}")


def main():
    # 定义静态资源映射
    files = {
        'css': {
            'github-markdown-light.min.css': 'https://cdnjs.cloudflare.com/ajax/libs/github-markdown-css/5.2.0/github-markdown-light.min.css',
            'github-markdown-dark.min.css': 'https://cdnjs.cloudflare.com/ajax/libs/github-markdown-css/5.2.0/github-markdown-dark.min.css',
            'default.min.css': 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.7.0/styles/default.min.css',
            'atom-one-dark.min.css': 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.7.0/styles/atom-one-dark.min.css',
            'github.min.css': 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.7.0/styles/github.min.css',
            'katex.min.css': 'https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.15.3/katex.min.css',
        },
        'js': {
            'highlight.min.js': 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.7.0/highlight.min.js',
            'katex.min.js': 'https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.15.3/katex.min.js',
            'auto-render.min.js': 'https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.15.3/contrib/auto-render.min.js',
        }
    }

    # 获取目录路径
    css_dir, js_dir = ensure_directories()

    # 下载 CSS 文件
    for filename, url in files['css'].items():
        dest_path = os.path.join(css_dir, filename)
        try:
            download_file(url, dest_path)
        except Exception as e:
            print(f"下载 {filename} 失败：{e}")

    # 下载 JS 文件
    for filename, url in files['js'].items():
        dest_path = os.path.join(js_dir, filename)
        try:
            download_file(url, dest_path)
        except Exception as e:
            print(f"下载 {filename} 失败：{e}")


if __name__ == '__main__':
    main()
