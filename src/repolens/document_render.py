"""Browser network broker: only this process can perform policy-checked HTTPS GETs."""
import base64
import os
import socket
import time
from repolens.document_network import DocumentError
from repolens.render_protocol import send,receive


def render_document(settings,fetcher,response):
    if os.name!='posix' or not settings.renderer_socket:raise DocumentError('renderer_unavailable')
    try:
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as conn:
            conn.settimeout(max(.001,fetcher.deadline-time.monotonic()))
            conn.connect(str(settings.renderer_socket))
            with conn.makefile('rwb') as stream:
                send(stream,{'op':'render','url':response['url'],'html':base64.b64encode(response['body']).decode(),'content_type':response['content_type']})
                while True:
                    fetcher.check();conn.settimeout(max(.001,fetcher.deadline-time.monotonic()))
                    message=receive(stream)
                    if message.get('op')=='result':
                        text=message.get('text')
                        if not isinstance(text,str) or not text.strip() or len(text.encode())>256*1024:raise DocumentError('renderer_text_invalid')
                        if message.get('incomplete'):raise DocumentError('renderer_resource_failed')
                        return text
                    if message.get('op')!='fetch' or not isinstance(message.get('url'),str):raise DocumentError('renderer_protocol_error')
                    try:
                        resource=fetcher.fetch(message['url'],resource=True)
                        send(stream,{'ok':True,'body':base64.b64encode(resource['body']).decode(),'content_type':resource['content_type']})
                    except DocumentError:send(stream,{'ok':False})
    except DocumentError:raise
    except (OSError,ValueError,TimeoutError):raise DocumentError('renderer_unavailable') from None
