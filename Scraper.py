import requests
from bs4 import BeautifulSoup
import os
import urllib.parse
import threading
from PIL import Image, UnidentifiedImageError
from fpdf import FPDF
from PyPDF2 import PdfMerger
import shutil, time
from concurrent.futures import ThreadPoolExecutor

DIR = os.getcwd()


def page_links(url) -> list:
    try:
        r = requests.get(url)
        soup = BeautifulSoup(r.content, 'html.parser')
        div = str(soup.find("div", {"class": "container-chapter-reader"}))
        images = BeautifulSoup(div, 'html.parser').find_all("img")
        page_urls = [image["src"] for image in images]
        return page_urls
    except requests.exceptions.RequestException:
        print("Error Fetching Page Links")


def download_image(name, url):
    retry_attempts = 5
    for attempt in range(retry_attempts):
        try:
            domain = urllib.parse.urlparse(url).netloc
            headers = {
                'Accept': 'image/webp,image/png,image/*;q=0.8,video/*;q=0.8,*/*;q=0.5',
                'Accept-Encoding': 'gzip, deflate, br',
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.1.2 Safari/605.1.15',
                'Host': domain, 'Accept-Language': 'en-ca', 'Referer': 'https://manganelo.com/',
                'Connection': 'keep-alive'
            }
            r = requests.get(url, headers=headers, stream=True)

            if r.status_code != 200:
                raise Exception(f"HTTP error: {r.status_code}")

            content_type = r.headers.get('Content-Type')
            if not content_type or 'image' not in content_type:
                raise Exception(f"Invalid content type: {content_type}")

            # Save the response content to a file (as WEBP, PNG, or other format)
            with open(name, 'wb') as f:
                f.write(r.content)

            # Verify if the image is valid
            with Image.open(name) as img:
                img.verify()

            break  # Break the loop if download is successful
        except (requests.exceptions.RequestException, UnidentifiedImageError, Exception) as e:
            print(f"Error downloading image {name} from {url}: {e}")
            if os.path.exists(name):
                os.remove(name)
            if attempt < retry_attempts - 1:
                time.sleep(2 ** attempt)
            else:
                # Save error response for analysis
                error_filename = f"error_{name}.html"
                with open(error_filename, 'wb') as f:
                    f.write(r.content)
                print(f"Saved error response content to {error_filename}")


def resize_image_to_width(image_path, target_width):
    """
    Resize the image to the target width while maintaining the aspect ratio.
    :param image_path: Path to the image to be resized.
    :param target_width: The target width to resize the image to.
    :return: Path to the resized image.
    """
    try:
        with Image.open(image_path) as img:
            # Calculate the aspect ratio
            width, height = img.size
            target_height = int((target_width / float(width)) * height)

            # Resize the image to the target width while keeping the aspect ratio
            img = img.resize((target_width, target_height), Image.Resampling.LANCZOS)

            # Save the resized image (replace original file with resized version)
            resized_image_path = image_path.replace('.webp', '_resized.jpg')  # Save with "_resized" suffix
            img.save(resized_image_path, 'JPEG', quality=85, optimize=True)

            return resized_image_path
    except Exception as e:
        print(f"Error resizing image {image_path}: {e}")
        return image_path  # Return original if resizing fails


def batch_resize_images(image_paths, target_width):
    """
    Resize all images in parallel using threading.
    :param image_paths: List of paths to the images to be resized.
    :param target_width: The target width to resize the images to.
    :return: List of resized image paths.
    """
    resized_image_paths = []

    with ThreadPoolExecutor() as executor:
        resized_image_paths = list(executor.map(lambda img: resize_image_to_width(img, target_width), image_paths))

    return resized_image_paths


def convert_to_pdf(name, imgs, pdfs, path, output_dir):
    """
    Convert the images to a single PDF with uniform image width.
    :param name: The name of the chapter.
    :param imgs: List of image paths.
    :param pdfs: List of intermediate PDF paths.
    :param path: Temporary directory path for images.
    :param output_dir: Output directory for the final PDF.
    """
    try:
        # Get the width of the first image (to set as the target width)
        with Image.open(imgs[0]) as img:
            target_width = img.size[0]  # Use the width of the first image as the target width
    except Exception as e:
        print(f"Error reading first image: {e}")
        return

    # Batch resize images in parallel
    resized_images = batch_resize_images(imgs, target_width)

    i = 0
    for img in resized_images:
        if os.path.exists(img):
            try:
                cover = Image.open(img)
                width, height = cover.size
                width, height = float(width * 0.264583), float(height * 0.264583)  # Convert pixels to mm for FPDF

                # Create a PDF page with the resized image
                pdf = FPDF('P', 'mm', (width, height))
                pdf.add_page()
                pdf.image(img, 0, 0, width, height)
                pdf.output(pdfs[i])

                # Clean up resized image after using it
                os.remove(img)

                i += 1
            except UnidentifiedImageError as e:
                print(f"Error processing image {img}: {e}")
                continue  # Skip the problematic image
        else:
            print(f"File not found: {img}, skipping.")

    merger = PdfMerger()
    for pdf in pdfs:
        if os.path.exists(pdf):
            merger.append(pdf)
        else:
            print(f"PDF file not found: {pdf}, skipping.")

    output_pdf_path = os.path.join(output_dir, f"{name}.pdf")
    merger.write(output_pdf_path)
    merger.close()
    for pdf in pdfs:
        if os.path.exists(pdf):
            os.remove(pdf)
    shutil.rmtree(path)
    print(f"Downloaded and converted {name} successfully")


def download_all_images(urls):
    threads = []
    for i in range(len(urls)):
        t = threading.Thread(target=download_image, args=(str(i + 1) + ".webp", urls[i]))  # Download as WEBP
        threads.append(t)
        t.start()
    for thread in threads:
        thread.join()


def download_chapter(name, url, output_dir):
    pages = page_links(url)
    n = len(pages)
    path = os.path.join(DIR, "Temp")
    if not os.path.exists(path):
        os.mkdir(path)
    os.chdir(path)
    download_all_images(pages)
    images = [str(i + 1) + '.webp' for i in range(n)]  # Keep images as WEBP
    pdfs = [str(i + 1) + '.pdf' for i in range(n)]
    convert_to_pdf(name, images, pdfs, path, output_dir)


def chapter_links(url) -> dict:
    try:
        r = requests.get(url)
        soup = BeautifulSoup(r.content, 'html.parser')
        chapters = soup.find_all("a", {"class": "chapter-name text-nowrap"})
        links = {chapter.text.strip(): chapter['href'] for chapter in chapters}
        return links
    except requests.exceptions.RequestException:
        print("Error Fetching Chapter Links")


def main():
    url = input("Enter Comic URL: ")
    title = input("Enter Comic Title: ").title()
    path = os.path.join(os.path.expanduser('~'), 'Documents/Comics/', title)
    if not os.path.exists(path):
        os.mkdir(path)
    chapters = chapter_links(url)
    for chapter in chapters:
        download_chapter(chapter, chapters[chapter], path)


main()
