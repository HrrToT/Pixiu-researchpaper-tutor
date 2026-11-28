"""Source-locating section references are not requested numeric answer objects."""
import re


def without_section_locators(text):
    # A direct request for the section identity keeps the existing exact check.
    if re.search(r'章节号|章号|节号|第几[章节]|编号|\b(?:section|chapter)\s+(?:number|identifier)|\bwhich\s+(?:section|chapter)\b',text,re.I):
        return text
    number=r'\d+(?:\.\d+){0,3}'
    text=re.sub(r'第\s*'+number+r'\s*[节章](?=中|里|内|的|所)', '',text)
    text=re.sub(r'\b(?:in|within|from|under)\s+(?:section|chapter)\s+'+number+r'(?![\d.])\b','',text,flags=re.I)
    return re.sub(r'\b(?:section|chapter)\s+'+number+r"(?![\d.])(?:'s|’s)\s*",'',text,flags=re.I)
