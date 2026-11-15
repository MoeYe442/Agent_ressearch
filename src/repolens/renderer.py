"""Optional Playwright sidecar. Must be deployed with network_mode:none, no secrets/data."""
import base64
import multiprocessing
import os
from pathlib import Path
import signal
import socket
from repolens.render_protocol import send,receive


def render(conn):
    os.setsid()
    from playwright.sync_api import sync_playwright
    conn.settimeout(30)
    with conn,conn.makefile('rwb') as stream:
        request=receive(stream)
        if request.get('op')!='render' or not isinstance(request.get('url'),str):return
        url=request['url'];body=base64.b64decode(request.get('html',''),validate=True)
        if len(body)>2*1024*1024 or not url.startswith('https://'):return
        incomplete=[]
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,chromium_sandbox=True,args=['--disable-dev-shm-usage','--force-webrtc-ip-handling-policy=disable_non_proxied_udp'])
            try:
                context=browser.new_context(service_workers='block',accept_downloads=False)
                context.set_default_timeout(20000)
                page=context.new_page()
                page.on('pageerror',lambda error:incomplete.append(True))
                def request_failed(req):
                    # Intentionally omitted images/fonts/media do not invalidate
                    # text rendering; failed active resources do.
                    if req.resource_type in {'document','script','stylesheet','fetch','xhr'}:incomplete.append(True)
                context.on('requestfailed',request_failed)
                def close_popup(popup):
                    if popup!=page:incomplete.append(True);popup.close()
                context.on('page',close_popup)
                def route(handler):
                    req=handler.request
                    if req.method!='GET' or not req.url.startswith('https://') or req.resource_type not in {'document','script','stylesheet','fetch','xhr'}:
                        if req.resource_type not in {'image','font','media'}:incomplete.append(True)
                        handler.abort();return
                    if req.resource_type=='document':
                        if req.frame!=page.main_frame or req.url!=url:handler.abort();incomplete.append(True);return
                        handler.fulfill(status=200,content_type=request['content_type'],body=body);return
                    send(stream,{'op':'fetch','url':req.url});reply=receive(stream)
                    if not reply.get('ok'):handler.abort();incomplete.append(True);return
                    handler.fulfill(status=200,content_type=reply['content_type'],body=base64.b64decode(reply['body'],validate=True))
                context.route('**/*',route)
                def close_websocket(websocket):incomplete.append(True);websocket.close()
                context.route_web_socket('**/*',close_websocket)
                page.goto(url,wait_until='domcontentloaded',timeout=20000)
                try:page.wait_for_load_state('networkidle',timeout=3000)
                except Exception:incomplete.append(True)
                value=page.evaluate("""() => { for(const el of document.querySelectorAll('script,style,noscript,nav,header,footer,aside,form,iframe')) el.remove(); const text=document.body?.innerText||''; return {text:text.slice(0,200000),tooLong:text.length>200000}; }""")
                send(stream,{'op':'result','text':value['text'],'incomplete':bool(incomplete) or value['tooLong']})
            finally:browser.close()


def main():
    if os.name!='posix':raise RuntimeError('renderer_requires_linux_isolation')
    if any(name!='lo' for _,name in socket.if_nameindex()):raise RuntimeError('renderer_requires_disabled_network')
    path=Path(os.getenv('REPOLENS_RENDERER_SOCKET','/run/repolens-render/browser.sock'))
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if not path.is_socket():raise RuntimeError('renderer_socket_path_occupied')
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as probe:
            try:probe.connect(str(path))
            except ConnectionRefusedError:path.unlink()
            else:raise RuntimeError('renderer_already_running')
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as server:
        server.bind(str(path));os.chmod(path,0o600);server.listen(4)
        while True:
            conn,_=server.accept()
            child=multiprocessing.get_context('fork').Process(target=render,args=(conn,));child.start();conn.close()
            child.join(32)
            if child.is_alive():child.terminate();child.join(2)
            try:os.killpg(child.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            if child.is_alive():child.kill();child.join()


if __name__=='__main__':main()
