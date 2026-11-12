"""Synthetic paired fixture: exercises tools, never measures model quality."""
import json
from tests.collaborative_model import CollaborativeModel
from repolens.models import ModelTurn, ModelUsage, ToolCall


class ComparisonModel(CollaborativeModel):
    def complete(self,messages,tools,max_output_tokens):
        system=messages[0]['content']
        if 'ROLE: planner' in system or 'ROLE: reviewer' in system:
            if 'ROLE: reviewer' in system:
                data=json.loads(messages[1]['content'])
                conflict=any('冲突' in claim['text'] for claim in data['claims'])
                return self.turn({'items':[{'claim_id':c['claim_id'],'verdict':'contradicted' if conflict else 'supported','evidence_ids':c['evidence_ids'],'reason':'Synthetic fixture judgement; manual review pending.'} for c in data['claims']],'followups':[]})
            return super().complete(messages,tools,max_output_tokens)
        question=messages[1]['content']
        docs='ROLE: docs' in system
        single='ROLE: single' in system
        path='app.py' if '入口' in question or '不存在' in question else 'storage.py'
        paths=['README.md'] if docs else [path,'README.md'] if single else [path]
        returned=[m for m in messages if m['role']=='tool']
        if not returned:
            return ModelTurn(tool_calls=[ToolCall(id=str(i),name='read_file',arguments={'path':p,'start_line':1,'end_line':7 if p=='README.md' else 15 if p=='app.py' else 12}) for i,p in enumerate(paths)],usage=ModelUsage(input_tokens=100,output_tokens=30))
        ids=[e for m in returned for e in json.loads(m['content']).get('evidence_ids',[])]
        text='app.main 创建 Processor 并调用 run。' if '入口' in question else '在限定文件中未发现多 Agent 调度；静态检索不能穷尽证明不存在。' if '不存在' in question else '冲突：README 声称自动恢复，代码仅在实例字典中存储，无重启恢复实现。' if '冲突' in question else 'StateStore.save 写入实例 states 字典，load 仅读取内存；未实现磁盘持久化与重启恢复。'
        return self.turn({'claims':[{'text':('文档写明：'+text) if docs else text,'evidence_ids':ids}],'limitations':['Synthetic fixture only；静态范围有限，恢复与不存在性须人工复查。']})
