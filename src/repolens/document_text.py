"""Deterministic bounded paragraph extraction. No scripts, remote URLs or markup execution."""
from html.parser import HTMLParser
import re
from repolens.document_network import DocumentError


class Extractor(HTMLParser):
    ignored={'script','style','noscript','svg','canvas','form','nav','header','footer','aside','template','iframe','object'}
    blocks={'p','div','section','article','h1','h2','h3','h4','h5','h6','li','pre','tr','br','hr'}
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth=0;self.parts=[];self.paragraphs=[];self.in_title=False;self.title=[]
    def flush(self):
        value=re.sub(r'\s+',' ',''.join(self.parts)).strip();self.parts=[]
        if value:self.paragraphs.append(value)
    def handle_starttag(self,tag,attrs):
        if tag=='title':self.in_title=True
        if tag in self.ignored:self.depth+=1
        if not self.depth and tag in self.blocks:self.flush()
    def handle_endtag(self,tag):
        if tag=='title':self.in_title=False
        if tag in self.ignored:self.depth=max(0,self.depth-1)
        if not self.depth and tag in self.blocks:self.flush()
    def handle_data(self,data):
        if self.in_title:self.title.append(data)
        elif not self.depth:self.parts.append(data)


def extract(body,content_type):
    try:text=body.decode('utf-8-sig')
    except UnicodeError:raise DocumentError('document_charset_unsupported') from None
    if content_type in {'text/html','application/xhtml+xml'}:
        parser=Extractor();parser.feed(text);parser.flush()
        paragraphs=parser.paragraphs;title=' '.join(parser.title).strip()[:300]
    else:paragraphs=[re.sub(r'\s+',' ',line).strip() for line in text.splitlines() if line.strip()];title=''
    paragraphs=[part[offset:offset+4000] for part in paragraphs for offset in range(0,len(part),4000)]
    if len(paragraphs)>2000 or len('\n'.join(paragraphs).encode())>256*1024:raise DocumentError('document_text_limit')
    return title,paragraphs
