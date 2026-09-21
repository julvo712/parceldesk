from datetime import date
from pydantic import BaseModel, ConfigDict, Field
class Strict(BaseModel): model_config=ConfigDict(extra='forbid')
class Order(Strict): order_id:str=Field(min_length=1,max_length=64)
class Empty(Strict): pass
class Shipping(Order): requested_by:date|None=Field(default=None,description="Requested arrival deadline as ISO calendar date YYYY-MM-DD; never customer identity")
class Create(Strict):
    proposal_id:str=Field(min_length=1,max_length=128)
    idempotency_key:str=Field(min_length=1,max_length=128)
class Send(Strict):
    replacement_id:str=Field(min_length=1,max_length=128)
    to:str=Field(min_length=3,max_length=254)
    idempotency_key:str=Field(min_length=1,max_length=128)
    body:str=Field(default='',max_length=4000)
MODELS={'get_order':Order,'get_retailer_policy':Empty,'get_supplier_guide':Order,'check_inventory':Order,'get_shipping_options':Shipping,'propose_replacement':Shipping,'create_replacement':Create,'send_confirmation':Send}
DESCRIPTIONS={'get_order':'Read the selected customer order and delivery date.','get_retailer_policy':'Read trusted retailer replacement policy.','get_supplier_guide':'Read the supplier product handling document.','check_inventory':'Check replacement stock for this order.','get_shipping_options':'Read actual carrier arrival estimate and deadline status.','propose_replacement':'Persist an eligible replacement proposal. Does not execute it. Customer must confirm in UI.','create_replacement':'Execute an already confirmed proposal with an idempotency key.','send_confirmation':'Record a sandbox notification for an executed replacement, only to the stored customer address.'}
DEFINITIONS=[{'name':k,'description':DESCRIPTIONS[k],'input_schema':v.model_json_schema()} for k,v in MODELS.items()]
def validate(name,arguments):
    if name not in MODELS: raise ValueError('Unknown tool')
    return MODELS[name].model_validate(arguments).model_dump(mode="json",exclude_none=True)
