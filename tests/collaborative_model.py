import json
import threading
import time
from repolens.models import ModelTurn,ModelUsage,ToolCall


class CollaborativeModel:
    """Role-aware fixture protocol only; never part of production modules."""
    def __init__(self,followups=0,repeat=False,conflict=False,fail_docs=False):
        self.followups,self.repeat,self.conflict,self.fail_docs=followups,repeat,conflict,fail_docs
        self.lock=threading.Lock();self.active=0;self.peak=0

    def complete(self,messages,tools,max_output_tokens):
        system=messages[0]['content']
        if 'ROLE: planner' in system:
            return self.turn({'tasks':[{'id':'code','role':'code','question':'Read the entry implementation','depends_on':[]},{'id':'docs','role':'docs','question':'Read project documentation','depends_on':[]}]})
        if 'ROLE: reviewer' in system:
            data=json.loads(messages[1]['content'])
            unresolved=data['round']<self.followups or self.conflict
            return self.turn({'items':[{'claim_id':c['claim_id'],'verdict':'contradicted' if self.conflict else 'insufficient' if unresolved else 'supported','evidence_ids':c['evidence_ids'],'reason':'Fixture semantic judgement only'} for c in data['claims']], 'followups':[{'role':'code','question':f'Inspect storage round {data["round"]+1}'}] if unresolved else []})
        docs='ROLE: docs' in system
        if docs and self.fail_docs:
            from repolens.model_client import ProviderError
            raise ProviderError('fixture_docs_unavailable')
        with self.lock:
            self.active+=1;self.peak=max(self.peak,self.active)
        time.sleep(.015)
        with self.lock:self.active-=1
        tool_messages=[m for m in messages if m['role']=='tool']
        if not tool_messages:
            question=messages[1]['content']
            path='README.md' if docs else 'storage.py' if 'Inspect storage' in question and not self.repeat else 'app.py'
            start=1 if docs else 4 if 'round 2' in question and not self.repeat else 1 if path=='storage.py' else 9
            end=3 if docs else 12 if start==4 else 3 if path=='storage.py' else 11
            return ModelTurn(tool_calls=[ToolCall(id='read',name='read_file',arguments={'path':path,'start_line':start,'end_line':end})],usage=ModelUsage(input_tokens=100,output_tokens=20))
        result=json.loads(tool_messages[-1]['content'])
        return self.turn({'claims':[{'text':'README describes entry and memory storage.' if docs else 'Processor delegates state updates to the store.','evidence_ids':result['evidence_ids']}], 'limitations':['Synthetic fixture; not a real model result.']})

    @staticmethod
    def turn(data):
        return ModelTurn(content=json.dumps(data,ensure_ascii=False),usage=ModelUsage(input_tokens=150,output_tokens=40))
