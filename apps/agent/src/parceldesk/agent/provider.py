"""Provider adapters share a bounded tool loop; each call is recorded exactly once."""
import json,uuid
from types import SimpleNamespace
from pydantic import BaseModel
from .. import config
class Block(BaseModel):
    type:str
    text:str|None=None
    id:str|None=None
    name:str|None=None
    input:dict|None=None

def ensure_gemini_tool_ids(response):
    """Attach correlation IDs before the observability wrapper records the response."""
    for candidate in response.candidates or []:
        if candidate.content:
            for part in candidate.content.parts or []:
                if part.function_call and not part.function_call.id:
                    part.function_call.id = str(uuid.uuid4())
    return response


class Provider:
    def __init__(self):
        if config.PROVIDER=='gemini':
            from google import genai
            self.client=genai.Client(api_key=config.GEMINI_KEY)
        elif config.PROVIDER=='openai':
            from openai import AsyncOpenAI
            self.client=AsyncOpenAI(api_key=config.OPENAI_KEY,timeout=35,max_retries=1)
        else:
            from anthropic import AsyncAnthropic
            self.client=AsyncAnthropic(api_key=config.ANTHROPIC_KEY,timeout=35,max_retries=1)
    async def generate(self,observer,request,ctx):
        common={'conversation_id':ctx['conversation_id'],'agent_name':'parceldesk-replacement','agent_version':ctx['agent_version'],'tags':{'traffic_kind':ctx['traffic_kind'],'scenario':ctx.get('scenario','healthy')},'metadata':{'demo_run_id':ctx['demo_run_id']}}
        if config.PROVIDER=='anthropic':
            from agento11y_anthropic import messages,AnthropicOptions
            return await messages.create_async(observer,request,lambda req:self.client.messages.create(**req),AnthropicOptions(**common))
        if config.PROVIDER=='gemini':
            from google.genai import types
            from agento11y_gemini import models,GeminiOptions
            names={b.get('id'):b.get('name') for m in request['messages'] if isinstance(m['content'],list) for b in m['content'] if b.get('type')=='tool_use'}
            contents=[]
            for m in request['messages']:
                parts=[];content=m['content']
                if isinstance(content,str):parts=[types.Part(text=content)]
                else:
                    for b in content:
                        if b['type']=='text':parts.append(types.Part(text=b['text']))
                        elif b['type']=='tool_use':parts.append(types.Part(function_call=types.FunctionCall(id=b['id'],name=b['name'],args=b['input'])))
                        elif b['type']=='tool_result':parts.append(types.Part(function_response=types.FunctionResponse(id=b['tool_use_id'],name=names[b['tool_use_id']],response={'result':b['content']})))
                contents.append(types.Content(role='model' if m['role']=='assistant' else 'user',parts=parts))
            funcs=[types.FunctionDeclaration(name=t['name'],description=t['description'],parameters_json_schema=t['input_schema']) for t in request['tools']]
            cfg=types.GenerateContentConfig(system_instruction=request['system'],max_output_tokens=request['max_tokens'],temperature=0,thinking_config=types.ThinkingConfig(thinking_budget=0),tools=[types.Tool(function_declarations=funcs)] if funcs else None,automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
            async def invoke(model, contents, generation_config):
                result=await self.client.aio.models.generate_content(model=model,contents=contents,config=generation_config)
                return ensure_gemini_tool_ids(result)
            r=await models.generate_content_async(observer,request['model'],contents,cfg,invoke,GeminiOptions(**common))
            blocks=[]
            if not r.candidates or not r.candidates[0].content:raise RuntimeError('Model returned no content')
            for p in r.candidates[0].content.parts:
                if p.text and not p.thought:blocks.append(Block(type='text',text=p.text))
                if p.function_call:
                    f=p.function_call;blocks.append(Block(type='tool_use',id=f.id,name=f.name,input=dict(f.args or {})))
            u=r.usage_metadata
            return SimpleNamespace(content=blocks,usage=SimpleNamespace(input_tokens=u.prompt_token_count or 0,output_tokens=u.candidates_token_count or 0,cache_read_input_tokens=u.cached_content_token_count,cache_creation_input_tokens=None),model_version=r.model_version)
        from agento11y_openai import responses,OpenAIOptions
        inputs=[]
        for m in request['messages']:
            if isinstance(m['content'],str):inputs.append({'role':m['role'],'content':m['content']});continue
            for b in m['content']:
                if b['type']=='text':inputs.append({'role':m['role'],'content':b['text']})
                elif b['type']=='tool_use':inputs.append({'type':'function_call','call_id':b['id'],'name':b['name'],'arguments':json.dumps(b['input'])})
                elif b['type']=='tool_result':inputs.append({'type':'function_call_output','call_id':b['tool_use_id'],'output':b['content']})
        req={'model':request['model'],'instructions':request['system'],'input':inputs,'max_output_tokens':request['max_tokens'],'tools':[{'type':'function','name':t['name'],'description':t['description'],'parameters':t['input_schema'],'strict':False} for t in request['tools']]}
        r=await responses.create_async(observer,req,lambda q:self.client.responses.create(**q),OpenAIOptions(**common))
        blocks=[]
        for b in r.output:
            if b.type=='function_call':blocks.append(Block(type='tool_use',id=b.call_id,name=b.name,input=json.loads(b.arguments)))
            elif b.type=='message':
                for p in b.content:
                    if p.type=='output_text':blocks.append(Block(type='text',text=p.text))
        return SimpleNamespace(content=blocks,usage=SimpleNamespace(input_tokens=r.usage.input_tokens,output_tokens=r.usage.output_tokens,cache_read_input_tokens=r.usage.input_tokens_details.cached_tokens,cache_creation_input_tokens=None))
    async def close(self):
        if config.PROVIDER=='gemini':await self.client.aio.aclose()
        else:await self.client.close()
