"""Size-limited JSON frames over a private local Unix socket."""
import json

MAX_FRAME=3*1024*1024


def send(stream,value):
    frame=json.dumps(value,ensure_ascii=True).encode()+b'\n'
    if len(frame)>MAX_FRAME:raise ValueError('render_frame_limit')
    stream.write(frame);stream.flush()


def receive(stream):
    frame=stream.readline(MAX_FRAME+1)
    if not frame or len(frame)>MAX_FRAME or not frame.endswith(b'\n'):raise ValueError('render_frame_limit')
    result=json.loads(frame)
    if not isinstance(result,dict):raise ValueError('render_protocol_error')
    return result
