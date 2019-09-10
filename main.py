import re
import base64
import json
import requests
from collections import OrderedDict
import time



def handle(event, context):
    order = get_order_options(event)
    template_url = order["name"]
    template_url = template_url.replace("https://github.com","https://raw.githubusercontent.com").replace("tree/","")
    service_catalog_name = order['service_catalog_name']
    service_catalog_desc = order['service_catalog_desc']
    template_name = template_url.rsplit('/', 1)[-1]
    metadata_content = get_github_content(template_url+"/metadata.json")
    metadata = json.loads(metadata_content)
    service_def_id = create_service_def(event,context, metadata,template_name,service_catalog_name,service_catalog_desc)

    file_content = get_github_content(template_url+"/metadata.json")
    bucket_name = upload_file_to_storage(context, service_def_id, file_content, "metadata.json")
    file_content = get_github_content(template_url+"/azuredeploy.json")
    upload_file_to_storage(context, service_def_id, file_content, "azuredeploy.json",bucket_name)

    order_id = event["order_id"]
    storage_path = "/storage/buckets/{}/{}".format(bucket_name,service_def_id) # storage path
    service_catalog_path = "https://webportal.ntt.com.sg/cmp/service-catalog/#/{}".format(service_def_id)
    update_order_with_multiple_options(context, order_id, "COMPLETED", ["Template Storage Location", "Service Catalog URL", "Service Catalog Name"," Service catalog Description"], [storage_path, service_catalog_path, service_catalog_name,service_catalog_desc])

    return "Successfully Created Service Catalog"
def schema(event,context):
    step = event.get("step")
    if not step:
        return get_template_name(event, context)
    if step in globals():
        return globals()[step](event, context)

def get_template_name(event,context):
    # "get_template_tag"
    questions = [
        {
            "help": "The Azure template name in Github",
            "label": "Template Github URL ",
            "id": "name",
            "validation": [
                {
                    "type": "required"
                },
            ],
            "type": "text",
            # "fieldset" : "Template Name"
        },
        {
            "help": "provide the service catalog name",
            "label": "Name",
            "id": "service_catalog_name",
            "validation": [
                {
                    "type": "required"
                }
            ],
            "type": "text",
            "fieldset" : "Service Catalog Details"
        },
        {
            "help": "provide the service catalog Description",
            "label": "Description",
            "id": "service_catalog_desc",
            "validation": [],
            "type": "textarea",
            "fieldset" : "Service Catalog Details"
        }
    ]
    resp = context.api.get("/service_tags")
    json_results = resp.json()
    for json_result in json_results:
        questions.append({
            "label": json_result["name"],
            "id": json_result["id"],
            "help": "Select Tag Name",
            "type": "checkbox",
            "fieldset" : "Tags"
        })
    return {
        "questions": questions,
        "previous_step": None,
        "current_step": "get_template_name",
        "next_step": None,
    }


def get_github_content(url):
    f = requests.get(url)
    return json.dumps(f.json(object_pairs_hook=OrderedDict))
    

def find_by_key(json_object, key, value):
    for obj in json_object:
        if obj[key] == value:
            return obj

def upload_file_to_storage(context, service_def_id, file_content, file_name,bucket_name = "azure-templates"):
    template_content = file_content
    timestamp = time.time()
    try:
        resp = context.api.put_file(
            path="/storage/buckets/{}/{}/{}".format(bucket_name,service_def_id, file_name),
            data=template_content
        )
    except Exception:
        try:
            context.api.put("/cmp/api/storage/buckets/"+str(bucket_name),{ "global_app_name": str(bucket_name), "type": "public" })
        except Exception:
            bucket_name = "azure-templates_"+timestamp
            context.api.put("/cmp/api/storage/buckets/"+str(bucket_name),{ "global_app_name": str(bucket_name), "type": "public" })
        finally:
            resp = context.api.put_file(
                path="/storage/buckets/{}/{}/{}".format(bucket_name,service_def_id, file_name),
                data=template_content
            )
    return bucket_name      
            
def create_service_def(event,context, metadata, template_name,service_catalog_name=None,service_catalog_desc=None):
    CATALOG_HANDLER_MODULE_ID = context.config["CATALOG_HANDLER_MODULE_ID"]
    WORKFLOW_EXECUTION_ID = context.config["WORKFLOW_EXECUTION_ID"]
    order = get_order_options(event)
    tags = []
    for key, value in order.items():
        if value is True:
            tags.append(key)

    service_def_resp = context.api.post(
        "/service_defs",
        {
            "name": service_catalog_name,
            "description": service_catalog_desc,
            # "questions": questions,
            "dynamic_schema": {
                "nflex_module_id": CATALOG_HANDLER_MODULE_ID,
                "handler": "main.schema"
            },
            "options": [
                {
                    "id": "provider_id",
                    "key": "Provider",
                    "val": "azure"
                },
                {
                    "id": "account_id",
                    "val": "bde77fc1-7df5-49b2-84db-d5bef608744c",
                    "label": "Azure Account Id",
                    "key": "Azure Account Id"
                },
                {
                    "id": "template",
                    "key": "Template Name",
                    "val": template_name
                }
            ],
            "tag_ids":  tags,
            "actions": {
                "create_order": {
                    "workflow_id": WORKFLOW_EXECUTION_ID,
                    "command": "run_workflow"
                },
            },
        },
    )
    if service_def_resp.status_code == requests.codes.created:
        json_resp = service_def_resp.json()
        service_def_id = json_resp["id"]
        return service_def_id

def get_order_options(event):
    return {opt["id"]: opt["val"] for opt in event.get("options", [])}

def update_order_with_multiple_options(context, order_id, status, option_labels=None, option_values=None):
    if order_id == None:
        raise Exception("Service catalog Order ID missing")
    context.log("Updating status/options for the Order: [{}]".format(order_id))
    resp = context.api.get("/orders/{}".format(order_id))
    json_result = resp.json()
    
    options = json_result["options"]
    payload = {
        "status": status,
    }
    active_tags = []
    for option in options:
        if option['val'] == True:
            active_tags.append(option['key'])
    tags = {
        "val": ', '.join(active_tags),
        "id": "Tag_list",
        "key": "Selected Tags"
    }
    options.append(tags)
    if option_labels:
        for option_label, option_value in zip(option_labels, option_values):
            options.append({
                "id": option_label,
                "key": option_label,
                "val": option_value,
            })
    payload["options"] = options
    resp = context.api.put("/orders/{}".format(order_id), payload)
    if resp.status_code != 200:
        context.log("Failed to update order: %s" % resp.text)
