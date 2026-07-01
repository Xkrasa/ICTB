# 编辑 gpt-image-2

POST

https://llm-api.net/v1/images/edits

Last modified:2 months ago

给定一个提示，该模型将返回一个或多个预测的完成，并且还可以返回每个位置的替代标记的概率。

为提供的提示和参数创建完成

官方文档：https://platform.openai.com/docs/api-reference/images/createEdit

## Request

Header Params

Acceptstring 

required

Example:application/json

Authorizationstring 

optional

Example:Bearer {{YOUR_API_KEY}}

Body Params multipart/form-data

imagefile 

required

要编辑的图片。必须是受支持的图片文件或图片数组。对于 gpt-image-1，每张图片应为小于 25MB 的 png、webp 或 jpg 文件。对于 dall-e-2，您只能提供一张图片，并且该图片应为小于 4MB 的方形 png 文件。

Example:["file://C:\\Users\\Administrator\\Desktop\\例子.png","file://C:\\Users\\Administrator\\Desktop\\场景2.png"]

promptstring 

required

所需图像的文本描述。dall-e-2 的最大长度为 1000 个字符，gpt-image-1 的最大长度为 32000 个字符。

Example:将他们合并在一个图片里面

maskstring 

optional

一张附加图片，其完全透明区域（例如，alpha 值为零）指示应编辑 image 位置。如果提供了多张图片，则遮罩将应用于第一张图片。必须是有效的 PNG 文件，小于 4MB，且尺寸与 image 相同。

modelstring 

optional

用于生成图像的模型。仅 gpt-image-1, gpt-image-1-all , flux-kontext-pro , flux-kontext-max。

Example:gpt-image-2-all

nstring 

optional

要生成的图像数量。必须介于 1 到 10 之间。

Example:1

qualitystring 

optional

生成图像的质量。只有 gpt-image-1 支持 high、medium 和 low 质量。dall-e-2 仅支持 standard 质量。默认为 auto。

response_formatstring 

optional

返回生成图像的格式。必须是 url 或 b64_json 之一。URL 在图像生成后 60 分钟内有效。此参数仅适用于 dall-e-2，因为 gpt-image-1 始终返回 base64 编码的图像，请不要使用这个参数。

Example:url

sizestring 

optional

生成图像的尺寸。对于 GPT 图像模型，必须是 1024x1024 、 1536x1024 （横版）、 1024x1536 （竖版）或 auto （默认值）之一，对于 dall-e-2 必须是 256x256 、 512x512 或 1024x1024 之一，对于 dall-e-3 必须是 1024x1024 、 1792x1024 或 1024x1792 之一。

Example:1024x1536

backgroundstring 

optional

允许为生成的图像的背景设置透明度。此参数仅在 gpt-image-1 中受支持。其值必须为 “透明（transparent）”、“不透明（opaque）” 或 “自动（auto）”（默认值）之一。当使用 “自动（auto）” 时，模型将自动为图像确定最佳背景。

Example:transparent

moderationstring 

optional

控制由 gpt-image-1 生成的图像的内容审核级别。可以设置为 “low” 以进行限制较少的过滤，也可以设置为 “auto”（默认值）。

Example:low

## Responses



🟢200OK

application/json

idstring 

required

objectstring 

required

createdinteger 

required



choicesarray [object] 

required

indexinteger 

optional



messageobject 

optional

finish_reasonstring 

optional



usageobject 

required

prompt_tokensinteger 

required

completion_tokensinteger 

required

total_tokensinteger 

required

Request



cURLcURL-WindowsHttpiewgetPowerShell

```
curl --location 'https://llm-api.net/v1/images/edits' \
--header 'Accept: application/json' \
--header 'Authorization: Bearer ' \
--form 'image=@"C:\\Users\\Administrator\\Desktop\\例子.png"' \
--form 'image=@"C:\\Users\\Administrator\\Desktop\\场景2.png"' \
--form 'prompt="将他们合并在一个图片里面"' \
--form 'model="gpt-image-2-all"' \
--form 'n="1"' \
--form 'size="1024x1536"'
```

Response



```
{
    "id": "chatcmpl-123",
    "object": "chat.completion",
    "created": 1677652288,
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "\n\nHello there, how may I assist you today?"
            },
            "finish_reason": "stop"
        }
    ],
    "usage": {
        "prompt_tokens": 9,
        "completion_tokens": 12,
        "total_tokens": 21
    }
}
```



# 创建 gpt-image-2

POST

https://llm-api.net/v1/images/generations

Last modified:10 days ago

给定一个提示，该模型将返回一个或多个预测的完成，并且还可以返回每个位置的替代标记的概率。

为提供的提示和参数创建完成

官方文档：https://platform.openai.com/docs/api-reference/images/create

TIP

只有使用官转以上的分组（也就是官转分组或分组单价比官转分组贵的）才能自定义分辨率

## Request

Header Params

Content-Typestring 

required

Example:application/json

Acceptstring 

required

Example:application/json

Authorizationstring 

optional

Example:Bearer {{YOUR_API_KEY}}

Body Paramsapplication/json

modalstring 

required

模型名

promptstring 

required

所需图像的文本描述。最大长度为 1000 个字符。

sizestring 

optional

图片尺寸
1024x1024 正方形
1536x1024 横版
1024x1536 竖版
2048x2048 2K正方形
2048x1152 2K横版
3840x2160 4K横版
2160x3840 4K竖版
auto 默认尺寸严格限制规则1.图片最大边长 ≤ 3840px2.宽高两边像素均为 16px 的倍数3.长边 / 短边 比值 ≤ 3:14.总像素范围：最小 655360 ~ 最大 8294400

formatstring 

optional

图片格式
可选：png 、 jpeg 、 webp

qualitystring 

optional

图片画质
可选：low 、 medium 、 high 、 auto（默认）

ninteger 

required

要生成的图像数。必须介于 1 和 10 之间。

Examples

## Responses



🟢200OK

application/json

idstring 

required

objectstring 

required

createdinteger 

required



choicesarray [object] 

required

indexinteger 

optional



messageobject 

optional

finish_reasonstring 

optional



usageobject 

required

prompt_tokensinteger 

required

completion_tokensinteger 

required

total_tokensinteger 

required

Request



cURLcURL-WindowsHttpiewgetPowerShell

```
curl --location 'https://llm-api.net/v1/images/generations' \
--header 'Accept: application/json' \
--header 'Authorization: Bearer ' \
--header 'Content-Type: application/json' \
--data '{
    "model": "gpt-image-2",
    "prompt": "A childrens book drawing of a veterinarian using a stethoscope to listen to the heartbeat of a baby otter.",
    "n": 1,
    "size": "1024x1024",
    "quality": "low",
    "format": "jpeg"
}'
```

Response



```
{
    "id": "chatcmpl-123",
    "object": "chat.completion",
    "created": 1677652288,
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "\n\nHello there, how may I assist you today?"
            },
            "finish_reason": "stop"
        }
    ],
    "usage": {
        "prompt_tokens": 9,
        "completion_tokens": 12,
        "total_tokens": 21
    }
}
```







gpt-image-2.0 rh低价版（文生图）

# 欢迎使用 RunningHub API，轻松调用 RunningHub 云端的 ComfyUI 工作流

## 1. 开始使用

### 注册用户

注册 RunningHub 账号并充值钱包后，即可开始使用 AI 应用 API 和 ComfyUI 工作流 API。
请注意：若您使用 消费级-会员 API Key，需拥有 基础版及以上会员 才能调用上述接口。
使用 企业级-共享 或 企业级-独占 API Key 的用户不受此限制。

### 获取您的 API Key

RunningHub 为每位用户自动生成一个独特的 32 位 API KEY

请妥善保存您的 API KEY，不要外泄，后续步骤将依赖此密钥进行操作

### 提交请求

提交 API 请求。RunningHub API 已为您处理 API Key，您只需提交请求即可

```curl
curl --location --request POST 'https://www.runninghub.cn/openapi/v2/run/ai-app/2046794551444119554' \
--header "Content-Type: application/json" \
--header "Authorization: Bearer ${RUNNINGHUB_API_KEY}" \
--data-raw '{
  "nodeInfoList": [
    {
      "nodeId": "18",
      "fieldName": "aspectRatio",
      "fieldData": "[[\"empty\", \"3:2\", \"1:1\", \"2:3\", \"5:4\", \"4:5\", \"16:9\", \"9:16\", \"21:9\", \"3:4\", \"4:3\"], {\"default\": \"empty\"}]",
      "fieldValue": "4:3",
      "description": "设置比例"
    },
    {
      "nodeId": "18",
      "fieldName": "resolution",
      "fieldData": "[[\"1k\", \"2k\", \"4k\"], {\"default\": \"1k\"}]",
      "fieldValue": "1k",
      "description": "分辨率"
    },
    {
      "nodeId": "18",
      "fieldName": "prompt",
      "fieldValue": "runninghub × 谷雨节气非遗皮影海报文案\n主视觉文案\n上方居中：LANDI POSTER DESIGN\n左上英文：Guyu Diary\n中间大字：谷雨・雨生百谷\n中间小字：Advanced plant pairing\n左下小字：春雨润田，谷生万物\n底部英文：Rain nourishes the fields, grains thrive in spring, inheriting the shadow puppetry heritage\n右下角小标：art‑landi\n底部版权：©2026 runninghub All rights reserved. 非遗皮影艺术联合呈现\n联动主题 slogan（适配海报角落 / 延展使用）\nrunninghub 踏春行・谷雨皮影映百谷\n非遗皮影承古韵，谷雨润田赴新程\n雨生万物，皮影传情，runninghub 伴四季",
      "description": "输入文本"
    }
  ],
  "instanceType": "default",
  "usePersonalQueue": "false"
}'
```

#### 请求参数说明

| 参数说明           | 类型    | 必填/可选 | AI 应用程序生成的结果。                                      |
| ------------------ | ------- | --------- | ------------------------------------------------------------ |
| `nodeInfoList`     | List    | 必填      | 节点参数映射列表，用于动态修改工作流参数                     |
| `instanceType`     | String  | 可选      | 指定运行实例的类型<br>default (24G显存), plus (48G显存)      |
| `usePersonalQueue` | Boolean | 可选      | 是否使用个人独占队列                                         |
| `retainSeconds`    | Integer | 可选      | 实例保留时长（秒）。仅企业共享 API Key 生效；任务成功结束后会在指定时长内优先复用同用户同工作流实例，减少冷启动与排队。该保留时段会产生额外费用，按实际保留时长计费。可选范围：10~180 秒。 |
| `webhookUrl`       | String  | 可选      | Webhook 回调地址，任务完成时会向该地址发送 POST 请求         |

#### 响应示例

```json
{
  "taskId": "2013508786110730241",
  "status": "RUNNING",
  "errorCode": "",
  "errorMessage": "",
  "results": null,
  "clientId": "f828b9af25161bc066ef152db7b29ccc",
  "promptTips": "{\"result\": true, \"error\": null, \"outputs_to_execute\": [\"4\"], \"node_errors\": {}}"
}
```

#### 响应字段说明

| 参数说明       | 类型          | AI 应用程序生成的结果。                                      |
| -------------- | ------------- | ------------------------------------------------------------ |
| `taskId`       | String        | 任务ID，用于后续查询任务状态                                 |
| `status`       | String        | 当前任务状态，常见状态：QUEUED (排队中), RUNNING (运行中), SUCCESS (成功), FAILED (失败) |
| `errorCode`    | String        | 错误码，仅在失败时返回                                       |
| `errorMessage` | String        | 错误具体信息                                                 |
| `results`      | List          | 生成结果（提交时为 null）                                    |
| ├ `url`        | String        | 重要提醒：该链接有效期仅为 24 小时。任务生成结束后，请务必在此时间窗口内将视频文件下载或转存至您的服务器。逾期后链接将永久失效且无法恢复。 |
| ├ `nodeId`     | String        | 生成该结果的工作流节点 ID                                    |
| ├ `outputType` | String        | 文件扩展名 (如 png, mp4, txt)                                |
| └ `text`       | String        | 如果输出是纯文本，内容将显示在此字段                         |
| `clientId`     | String        | 客户端会话ID，用于标识本次连接                               |
| `promptTips`   | String (JSON) | ComfyUI 后端的校验信息，包含需执行的节点ID等调试信息         |

### 查询结果与 Webhook

如果在提交时添加了 "webhookUrl": "https://example.com/webhook" 请求体参数，RunningHub 会在任务完成时向您的URL发送POST请求

#### 请求示例

```curl
curl --location --request POST 'https://www.runninghub.cn/openapi/v2/query' \
--header "Content-Type: application/json" \
--header "Authorization: Bearer ${RUNNINGHUB_API_KEY}" \
--data-raw '{
  "taskId": "${RUNNINGHUB_TASKID}"
}'
```

#### 响应示例

```json
{
  "taskId": "2013508786110730241",
  "status": "SUCCESS",
  "errorCode": "",
  "errorMessage": "",
  "failedReason": {},
  "usage": {
    "consumeMoney": null,
    "consumeCoins": null,
    "taskCostTime": "0",
    "thirdPartyConsumeMoney": null
  },
  "results": [
    {
      "url": "https://rh-images-1252422369.cos.ap-beijing.myqcloud.com/b04e28cad0ee39193921a30a2eb4dc00/output/ComfyUI_00001_plhjr_1768892915.png",
      "nodeId": "2",
      "outputType": "png",
      "text": null
    }
  ],
  "clientId": "",
  "promptTips": ""
}
```

#### 响应字段说明

| 参数说明                   | 类型   | AI 应用程序生成的结果。                                      |
| -------------------------- | ------ | ------------------------------------------------------------ |
| `taskId`                   | String | 任务 ID                                                      |
| `status`                   | String | 任务最终状态，SUCCESS 表示生成成功                           |
| `results`                  | List   | 生成结果列表，包含图片、视频或文本等输出                     |
| ├ `url`                    | String | 重要提醒：该链接有效期仅为 24 小时。任务生成结束后，请务必在此时间窗口内将视频文件下载或转存至您的服务器。逾期后链接将永久失效且无法恢复。 |
| ├ `nodeId`                 | String | 生成该结果的工作流节点 ID                                    |
| ├ `outputType`             | String | 文件扩展名 (如 png, mp4, txt)                                |
| └ `text`                   | String | 如果输出是纯文本，内容将显示在此字段                         |
| `errorCode`                | String | 错误码 (如有)                                                |
| `errorMessage`             | String | 错误信息 (如有)                                              |
| `failedReason`             | Object | ComfyUI 相关的失败原因                                       |
| `usage`                    | Object | 任务消耗信息                                                 |
| ├ `thirdPartyConsumeMoney` | String | 三方API消费金额                                              |
| ├ `consumeMoney`           | String | 运行时长消耗金额                                             |
| ├ `consumeCoins`           | String | 运行消耗的RH币                                               |
| └ `taskCostTime`           | String | 运行耗时（ComfyUI 工作流运行时长）                           |
### 文件上传

资源文件（如 imageUrls）参数支持传入文件 URL 或 Base64 Data URI。

#### 公共 URL

直接传递可公开访问的 URL：

```json
{
  "imageUrls": [
    "https://example.com/image.png"
  ]
}
```

#### Base64 data URI

以 Base64 格式嵌入图片：

```json
{
  "images": [
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA..."
  ]
}
```

#### RH 上传接口

上传本地文件以获取一个 URL。

**Endpoint:** `https://www.runninghub.cn/openapi/v2/media/upload/binary`

**请求**

```curl
curl --location --request POST 'https://www.runninghub.cn/openapi/v2/media/upload/binary' \
--header 'Authorization: Bearer [Your API KEY]' \
--form 'file=@/path/to/image.png'
```

**响应**

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "type": "image",
    "download_url": "xxxx.png",
    "fileName": "openapi/xxxx.png",
    "size": "3490"
  }
}
```

**备注:** 上传后获得的链接有效期为 1 天，超期将无法通过 URL 直接访问。





gpt-image-2.0 rh低价版（图生图）

# 欢迎使用 RunningHub API，轻松调用 RunningHub 云端的 ComfyUI 工作流

## 1. 开始使用

### 注册用户

注册 RunningHub 账号并充值钱包后，即可开始使用 AI 应用 API 和 ComfyUI 工作流 API。
请注意：若您使用 消费级-会员 API Key，需拥有 基础版及以上会员 才能调用上述接口。
使用 企业级-共享 或 企业级-独占 API Key 的用户不受此限制。

### 获取您的 API Key

RunningHub 为每位用户自动生成一个独特的 32 位 API KEY

请妥善保存您的 API KEY，不要外泄，后续步骤将依赖此密钥进行操作

### 提交请求

提交 API 请求。RunningHub API 已为您处理 API Key，您只需提交请求即可

```curl
curl --location --request POST 'https://www.runninghub.cn/openapi/v2/run/ai-app/2046794946094571522' \
--header "Content-Type: application/json" \
--header "Authorization: Bearer ${RUNNINGHUB_API_KEY}" \
--data-raw '{
  "nodeInfoList": [
    {
      "nodeId": "3",
      "fieldName": "image",
      "fieldValue": "00e448f616f92525c0ed90f92ca5d8dd0e803b5d730c66ff49e2cdcff0968655.png",
      "description": "上传图像1"
    },
    {
      "nodeId": "2",
      "fieldName": "image",
      "fieldValue": "f9e0f510b5b7a29a80547147af045cc75b338af36a6eee5953ca2b9844d37c48.png",
      "description": "上传图像2"
    },
    {
      "nodeId": "4",
      "fieldName": "aspectRatio",
      "fieldData": "[[\"empty\", \"3:2\", \"1:1\", \"2:3\", \"5:4\", \"4:5\", \"16:9\", \"9:16\", \"21:9\", \"3:4\", \"4:3\"], {\"default\": \"empty\"}]",
      "fieldValue": "9:16",
      "description": "设置比例"
    },
    {
      "nodeId": "4",
      "fieldName": "resolution",
      "fieldData": "[[\"1k\", \"2k\", \"4k\"], {\"default\": \"1k\"}]",
      "fieldValue": "1k",
      "description": "分辨率"
    },
    {
      "nodeId": "4",
      "fieldName": "prompt",
      "fieldValue": "图1的角色按照图2的排版生成新的Q版萌系3D IP全案设计",
      "description": "输入文本"
    }
  ],
  "instanceType": "default",
  "usePersonalQueue": "false"
}'
```

#### 请求参数说明

| 参数说明           | 类型    | 必填/可选 | AI 应用程序生成的结果。                                      |
| ------------------ | ------- | --------- | ------------------------------------------------------------ |
| `nodeInfoList`     | List    | 必填      | 节点参数映射列表，用于动态修改工作流参数                     |
| `instanceType`     | String  | 可选      | 指定运行实例的类型<br>default (24G显存), plus (48G显存)      |
| `usePersonalQueue` | Boolean | 可选      | 是否使用个人独占队列                                         |
| `retainSeconds`    | Integer | 可选      | 实例保留时长（秒）。仅企业共享 API Key 生效；任务成功结束后会在指定时长内优先复用同用户同工作流实例，减少冷启动与排队。该保留时段会产生额外费用，按实际保留时长计费。可选范围：10~180 秒。 |
| `webhookUrl`       | String  | 可选      | Webhook 回调地址，任务完成时会向该地址发送 POST 请求         |

#### 响应示例

```json
{
  "taskId": "2013508786110730241",
  "status": "RUNNING",
  "errorCode": "",
  "errorMessage": "",
  "results": null,
  "clientId": "f828b9af25161bc066ef152db7b29ccc",
  "promptTips": "{\"result\": true, \"error\": null, \"outputs_to_execute\": [\"4\"], \"node_errors\": {}}"
}
```

#### 响应字段说明

| 参数说明       | 类型          | AI 应用程序生成的结果。                                      |
| -------------- | ------------- | ------------------------------------------------------------ |
| `taskId`       | String        | 任务ID，用于后续查询任务状态                                 |
| `status`       | String        | 当前任务状态，常见状态：QUEUED (排队中), RUNNING (运行中), SUCCESS (成功), FAILED (失败) |
| `errorCode`    | String        | 错误码，仅在失败时返回                                       |
| `errorMessage` | String        | 错误具体信息                                                 |
| `results`      | List          | 生成结果（提交时为 null）                                    |
| ├ `url`        | String        | 重要提醒：该链接有效期仅为 24 小时。任务生成结束后，请务必在此时间窗口内将视频文件下载或转存至您的服务器。逾期后链接将永久失效且无法恢复。 |
| ├ `nodeId`     | String        | 生成该结果的工作流节点 ID                                    |
| ├ `outputType` | String        | 文件扩展名 (如 png, mp4, txt)                                |
| └ `text`       | String        | 如果输出是纯文本，内容将显示在此字段                         |
| `clientId`     | String        | 客户端会话ID，用于标识本次连接                               |
| `promptTips`   | String (JSON) | ComfyUI 后端的校验信息，包含需执行的节点ID等调试信息         |

### 查询结果与 Webhook

如果在提交时添加了 "webhookUrl": "https://example.com/webhook" 请求体参数，RunningHub 会在任务完成时向您的URL发送POST请求

#### 请求示例

```curl
curl --location --request POST 'https://www.runninghub.cn/openapi/v2/query' \
--header "Content-Type: application/json" \
--header "Authorization: Bearer ${RUNNINGHUB_API_KEY}" \
--data-raw '{
  "taskId": "${RUNNINGHUB_TASKID}"
}'
```

#### 响应示例

```json
{
  "taskId": "2013508786110730241",
  "status": "SUCCESS",
  "errorCode": "",
  "errorMessage": "",
  "failedReason": {},
  "usage": {
    "consumeMoney": null,
    "consumeCoins": null,
    "taskCostTime": "0",
    "thirdPartyConsumeMoney": null
  },
  "results": [
    {
      "url": "https://rh-images-1252422369.cos.ap-beijing.myqcloud.com/b04e28cad0ee39193921a30a2eb4dc00/output/ComfyUI_00001_plhjr_1768892915.png",
      "nodeId": "2",
      "outputType": "png",
      "text": null
    }
  ],
  "clientId": "",
  "promptTips": ""
}
```

#### 响应字段说明

| 参数说明                   | 类型   | AI 应用程序生成的结果。                                      |
| -------------------------- | ------ | ------------------------------------------------------------ |
| `taskId`                   | String | 任务 ID                                                      |
| `status`                   | String | 任务最终状态，SUCCESS 表示生成成功                           |
| `results`                  | List   | 生成结果列表，包含图片、视频或文本等输出                     |
| ├ `url`                    | String | 重要提醒：该链接有效期仅为 24 小时。任务生成结束后，请务必在此时间窗口内将视频文件下载或转存至您的服务器。逾期后链接将永久失效且无法恢复。 |
| ├ `nodeId`                 | String | 生成该结果的工作流节点 ID                                    |
| ├ `outputType`             | String | 文件扩展名 (如 png, mp4, txt)                                |
| └ `text`                   | String | 如果输出是纯文本，内容将显示在此字段                         |
| `errorCode`                | String | 错误码 (如有)                                                |
| `errorMessage`             | String | 错误信息 (如有)                                              |
| `failedReason`             | Object | ComfyUI 相关的失败原因                                       |
| `usage`                    | Object | 任务消耗信息                                                 |
| ├ `thirdPartyConsumeMoney` | String | 三方API消费金额                                              |
| ├ `consumeMoney`           | String | 运行时长消耗金额                                             |
| ├ `consumeCoins`           | String | 运行消耗的RH币                                               |
| └ `taskCostTime`           | String | 运行耗时（ComfyUI 工作流运行时长）                           |
### 文件上传

资源文件（如 imageUrls）参数支持传入文件 URL 或 Base64 Data URI。

#### 公共 URL

直接传递可公开访问的 URL：

```json
{
  "imageUrls": [
    "https://example.com/image.png"
  ]
}
```

#### Base64 data URI

以 Base64 格式嵌入图片：

```json
{
  "images": [
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA..."
  ]
}
```

#### RH 上传接口

上传本地文件以获取一个 URL。

**Endpoint:** `https://www.runninghub.cn/openapi/v2/media/upload/binary`

**请求**

```curl
curl --location --request POST 'https://www.runninghub.cn/openapi/v2/media/upload/binary' \
--header 'Authorization: Bearer [Your API KEY]' \
--form 'file=@/path/to/image.png'
```

**响应**

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "type": "image",
    "download_url": "xxxx.png",
    "fileName": "openapi/xxxx.png",
    "size": "3490"
  }
}
```

**备注:** 上传后获得的链接有效期为 1 天，超期将无法通过 URL 直接访问。







nano banana pro
# 欢迎使用 RunningHub API，轻松调用 RunningHub 云端的 ComfyUI 工作流

## 1. 开始使用

### 注册用户

注册 RunningHub 账号并充值钱包后，即可开始使用 AI 应用 API 和 ComfyUI 工作流 API。
请注意：若您使用 消费级-会员 API Key，需拥有 基础版及以上会员 才能调用上述接口。
使用 企业级-共享 或 企业级-独占 API Key 的用户不受此限制。

### 获取您的 API Key

RunningHub 为每位用户自动生成一个独特的 32 位 API KEY

请妥善保存您的 API KEY，不要外泄，后续步骤将依赖此密钥进行操作

### 提交请求

提交 API 请求。RunningHub API 已为您处理 API Key，您只需提交请求即可

```curl
curl --location --request POST 'https://www.runninghub.cn/openapi/v2/run/ai-app/1965678974313578497' \
--header "Content-Type: application/json" \
--header "Authorization: Bearer ${RUNNINGHUB_API_KEY}" \
--data-raw '{
  "nodeInfoList": [
    {
      "nodeId": "55",
      "fieldName": "image",
      "fieldValue": "79d062c5c11c23b26affe195a5e7623ca03e4abf32496becd498dfbcc669e345.jpeg",
      "description": "图像"
    },
    {
      "nodeId": "54",
      "fieldName": "text",
      "fieldValue": "图中人物的3/7比例商业模型已制作完成，其风格写实，环境逼真。模型放置在碳纤维桌面上。桌面上还有很多其他手办模型的小部件。电脑屏幕上显示着模型的Blender建模过程。电脑屏幕放着已经组装好的手办，正视角出现两只手拿着工具在制作手办。",
      "description": "提示词"
    },
    {
      "nodeId": "127",
      "fieldName": "resolution",
      "fieldData": "[[\"1k\", \"2k\", \"4k\"], {\"default\": \"2k\"}]",
      "fieldValue": "1k",
      "description": "分辨率"
    },
    {
      "nodeId": "127",
      "fieldName": "aspectRatio",
      "fieldData": "[[\"auto\", \"1:1\", \"1:4\", \"1:8\", \"2:3\", \"3:2\", \"3:4\", \"4:1\", \"4:3\", \"4:5\", \"5:4\", \"8:1\", \"9:16\", \"16:9\", \"21:9\"], {\"default\": \"4:3\"}]",
      "fieldValue": "9:16",
      "description": "尺寸比例"
    }
  ],
  "instanceType": "default",
  "usePersonalQueue": "false"
}'
```

#### 请求参数说明

| 参数说明           | 类型    | 必填/可选 | AI 应用程序生成的结果。                                      |
| ------------------ | ------- | --------- | ------------------------------------------------------------ |
| `nodeInfoList`     | List    | 必填      | 节点参数映射列表，用于动态修改工作流参数                     |
| `instanceType`     | String  | 可选      | 指定运行实例的类型<br>default (24G显存), plus (48G显存)      |
| `usePersonalQueue` | Boolean | 可选      | 是否使用个人独占队列                                         |
| `retainSeconds`    | Integer | 可选      | 实例保留时长（秒）。仅企业共享 API Key 生效；任务成功结束后会在指定时长内优先复用同用户同工作流实例，减少冷启动与排队。该保留时段会产生额外费用，按实际保留时长计费。可选范围：10~180 秒。 |
| `webhookUrl`       | String  | 可选      | Webhook 回调地址，任务完成时会向该地址发送 POST 请求         |

#### 响应示例

```json
{
  "taskId": "2013508786110730241",
  "status": "RUNNING",
  "errorCode": "",
  "errorMessage": "",
  "results": null,
  "clientId": "f828b9af25161bc066ef152db7b29ccc",
  "promptTips": "{\"result\": true, \"error\": null, \"outputs_to_execute\": [\"4\"], \"node_errors\": {}}"
}
```

#### 响应字段说明

| 参数说明       | 类型          | AI 应用程序生成的结果。                                      |
| -------------- | ------------- | ------------------------------------------------------------ |
| `taskId`       | String        | 任务ID，用于后续查询任务状态                                 |
| `status`       | String        | 当前任务状态，常见状态：QUEUED (排队中), RUNNING (运行中), SUCCESS (成功), FAILED (失败) |
| `errorCode`    | String        | 错误码，仅在失败时返回                                       |
| `errorMessage` | String        | 错误具体信息                                                 |
| `results`      | List          | 生成结果（提交时为 null）                                    |
| ├ `url`        | String        | 重要提醒：该链接有效期仅为 24 小时。任务生成结束后，请务必在此时间窗口内将视频文件下载或转存至您的服务器。逾期后链接将永久失效且无法恢复。 |
| ├ `nodeId`     | String        | 生成该结果的工作流节点 ID                                    |
| ├ `outputType` | String        | 文件扩展名 (如 png, mp4, txt)                                |
| └ `text`       | String        | 如果输出是纯文本，内容将显示在此字段                         |
| `clientId`     | String        | 客户端会话ID，用于标识本次连接                               |
| `promptTips`   | String (JSON) | ComfyUI 后端的校验信息，包含需执行的节点ID等调试信息         |

### 查询结果与 Webhook

如果在提交时添加了 "webhookUrl": "https://example.com/webhook" 请求体参数，RunningHub 会在任务完成时向您的URL发送POST请求

#### 请求示例

```curl
curl --location --request POST 'https://www.runninghub.cn/openapi/v2/query' \
--header "Content-Type: application/json" \
--header "Authorization: Bearer ${RUNNINGHUB_API_KEY}" \
--data-raw '{
  "taskId": "${RUNNINGHUB_TASKID}"
}'
```

#### 响应示例

```json
{
  "taskId": "2013508786110730241",
  "status": "SUCCESS",
  "errorCode": "",
  "errorMessage": "",
  "failedReason": {},
  "usage": {
    "consumeMoney": null,
    "consumeCoins": null,
    "taskCostTime": "0",
    "thirdPartyConsumeMoney": null
  },
  "results": [
    {
      "url": "https://rh-images-1252422369.cos.ap-beijing.myqcloud.com/b04e28cad0ee39193921a30a2eb4dc00/output/ComfyUI_00001_plhjr_1768892915.png",
      "nodeId": "2",
      "outputType": "png",
      "text": null
    }
  ],
  "clientId": "",
  "promptTips": ""
}
```

#### 响应字段说明

| 参数说明                   | 类型   | AI 应用程序生成的结果。                                      |
| -------------------------- | ------ | ------------------------------------------------------------ |
| `taskId`                   | String | 任务 ID                                                      |
| `status`                   | String | 任务最终状态，SUCCESS 表示生成成功                           |
| `results`                  | List   | 生成结果列表，包含图片、视频或文本等输出                     |
| ├ `url`                    | String | 重要提醒：该链接有效期仅为 24 小时。任务生成结束后，请务必在此时间窗口内将视频文件下载或转存至您的服务器。逾期后链接将永久失效且无法恢复。 |
| ├ `nodeId`                 | String | 生成该结果的工作流节点 ID                                    |
| ├ `outputType`             | String | 文件扩展名 (如 png, mp4, txt)                                |
| └ `text`                   | String | 如果输出是纯文本，内容将显示在此字段                         |
| `errorCode`                | String | 错误码 (如有)                                                |
| `errorMessage`             | String | 错误信息 (如有)                                              |
| `failedReason`             | Object | ComfyUI 相关的失败原因                                       |
| `usage`                    | Object | 任务消耗信息                                                 |
| ├ `thirdPartyConsumeMoney` | String | 三方API消费金额                                              |
| ├ `consumeMoney`           | String | 运行时长消耗金额                                             |
| ├ `consumeCoins`           | String | 运行消耗的RH币                                               |
| └ `taskCostTime`           | String | 运行耗时（ComfyUI 工作流运行时长）                           |
### 文件上传

资源文件（如 imageUrls）参数支持传入文件 URL 或 Base64 Data URI。

#### 公共 URL

直接传递可公开访问的 URL：

```json
{
  "imageUrls": [
    "https://example.com/image.png"
  ]
}
```

#### Base64 data URI

以 Base64 格式嵌入图片：

```json
{
  "images": [
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA..."
  ]
}
```

#### RH 上传接口

上传本地文件以获取一个 URL。

**Endpoint:** `https://www.runninghub.cn/openapi/v2/media/upload/binary`

**请求**

```curl
curl --location --request POST 'https://www.runninghub.cn/openapi/v2/media/upload/binary' \
--header 'Authorization: Bearer [Your API KEY]' \
--form 'file=@/path/to/image.png'
```

**响应**

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "type": "image",
    "download_url": "xxxx.png",
    "fileName": "openapi/xxxx.png",
    "size": "3490"
  }
}
```

**备注:** 上传后获得的链接有效期为 1 天，超期将无法通过 URL 直接访问。





nano banana 2.0

# 欢迎使用 RunningHub API，轻松调用 RunningHub 云端的 ComfyUI 工作流

## 1. 开始使用

### 注册用户

注册 RunningHub 账号并充值钱包后，即可开始使用 AI 应用 API 和 ComfyUI 工作流 API。
请注意：若您使用 消费级-会员 API Key，需拥有 基础版及以上会员 才能调用上述接口。
使用 企业级-共享 或 企业级-独占 API Key 的用户不受此限制。

### 获取您的 API Key

RunningHub 为每位用户自动生成一个独特的 32 位 API KEY

请妥善保存您的 API KEY，不要外泄，后续步骤将依赖此密钥进行操作

### 提交请求

提交 API 请求。RunningHub API 已为您处理 API Key，您只需提交请求即可

```curl
curl --location --request POST 'https://www.runninghub.cn/openapi/v2/run/ai-app/2067967606665076738' \
--header "Content-Type: application/json" \
--header "Authorization: Bearer ${RUNNINGHUB_API_KEY}" \
--data-raw '{
  "nodeInfoList": [
    {
      "nodeId": "3",
      "fieldName": "image",
      "fieldValue": "15b9273b8760cb2ebbc5216d493a956648f2de91c41b6c38b46409deb33d47ce.jpg",
      "description": "上传图像1（必填）"
    },
    {
      "nodeId": "4",
      "fieldName": "image",
      "fieldValue": "6f83b3cc0f7d18f4d086ba93c81f71fd8f42a3f0387a8053714cb51dc7b89eee.jpg",
      "description": "上传图像2（选填）"
    },
    {
      "nodeId": "5",
      "fieldName": "image",
      "fieldValue": "782e15c742959f852c4b9b0a1c638c1bfbb337e7920b5d35a6e2e870fd48d8b1.jpg",
      "description": "上传图像3（选填）"
    },
    {
      "nodeId": "6",
      "fieldName": "image",
      "fieldValue": "122720276bd3e9f5e67181f363c6af3ba01fe47652065d0253be335774160e45.jpg",
      "description": "上传图像4（选填）"
    },
    {
      "nodeId": "8",
      "fieldName": "aspectRatio",
      "fieldData": "[[\"empty\", \"1:1\", \"16:9\", \"9:16\", \"4:3\", \"3:4\", \"3:2\", \"2:3\", \"5:4\", \"4:5\", \"21:9\", \"1:4\", \"4:1\", \"1:8\", \"8:1\"], {\"default\": \"empty\"}]",
      "fieldValue": "16:9",
      "description": "比例"
    },
    {
      "nodeId": "8",
      "fieldName": "resolution",
      "fieldData": "[[\"1k\", \"2k\", \"4k\"], {\"default\": \"1k\"}]",
      "fieldValue": "2k",
      "description": "分辨率"
    },
    {
      "nodeId": "8",
      "fieldName": "prompt",
      "fieldValue": "参考这几张图，生成3✖️3图表，分镜MV9宫格的图，不要文字",
      "description": "输入文本"
    }
  ],
  "instanceType": "default",
  "usePersonalQueue": "false"
}'
```

#### 请求参数说明

| 参数说明           | 类型    | 必填/可选 | AI 应用程序生成的结果。                                      |
| ------------------ | ------- | --------- | ------------------------------------------------------------ |
| `nodeInfoList`     | List    | 必填      | 节点参数映射列表，用于动态修改工作流参数                     |
| `instanceType`     | String  | 可选      | 指定运行实例的类型<br>default (24G显存), plus (48G显存)      |
| `usePersonalQueue` | Boolean | 可选      | 是否使用个人独占队列                                         |
| `retainSeconds`    | Integer | 可选      | 实例保留时长（秒）。仅企业共享 API Key 生效；任务成功结束后会在指定时长内优先复用同用户同工作流实例，减少冷启动与排队。该保留时段会产生额外费用，按实际保留时长计费。可选范围：10~180 秒。 |
| `webhookUrl`       | String  | 可选      | Webhook 回调地址，任务完成时会向该地址发送 POST 请求         |

#### 响应示例

```json
{
  "taskId": "2013508786110730241",
  "status": "RUNNING",
  "errorCode": "",
  "errorMessage": "",
  "results": null,
  "clientId": "f828b9af25161bc066ef152db7b29ccc",
  "promptTips": "{\"result\": true, \"error\": null, \"outputs_to_execute\": [\"4\"], \"node_errors\": {}}"
}
```

#### 响应字段说明

| 参数说明       | 类型          | AI 应用程序生成的结果。                                      |
| -------------- | ------------- | ------------------------------------------------------------ |
| `taskId`       | String        | 任务ID，用于后续查询任务状态                                 |
| `status`       | String        | 当前任务状态，常见状态：QUEUED (排队中), RUNNING (运行中), SUCCESS (成功), FAILED (失败) |
| `errorCode`    | String        | 错误码，仅在失败时返回                                       |
| `errorMessage` | String        | 错误具体信息                                                 |
| `results`      | List          | 生成结果（提交时为 null）                                    |
| ├ `url`        | String        | 重要提醒：该链接有效期仅为 24 小时。任务生成结束后，请务必在此时间窗口内将视频文件下载或转存至您的服务器。逾期后链接将永久失效且无法恢复。 |
| ├ `nodeId`     | String        | 生成该结果的工作流节点 ID                                    |
| ├ `outputType` | String        | 文件扩展名 (如 png, mp4, txt)                                |
| └ `text`       | String        | 如果输出是纯文本，内容将显示在此字段                         |
| `clientId`     | String        | 客户端会话ID，用于标识本次连接                               |
| `promptTips`   | String (JSON) | ComfyUI 后端的校验信息，包含需执行的节点ID等调试信息         |

### 查询结果与 Webhook

如果在提交时添加了 "webhookUrl": "https://example.com/webhook" 请求体参数，RunningHub 会在任务完成时向您的URL发送POST请求

#### 请求示例

```curl
curl --location --request POST 'https://www.runninghub.cn/openapi/v2/query' \
--header "Content-Type: application/json" \
--header "Authorization: Bearer ${RUNNINGHUB_API_KEY}" \
--data-raw '{
  "taskId": "${RUNNINGHUB_TASKID}"
}'
```

#### 响应示例

```json
{
  "taskId": "2013508786110730241",
  "status": "SUCCESS",
  "errorCode": "",
  "errorMessage": "",
  "failedReason": {},
  "usage": {
    "consumeMoney": null,
    "consumeCoins": null,
    "taskCostTime": "0",
    "thirdPartyConsumeMoney": null
  },
  "results": [
    {
      "url": "https://rh-images-1252422369.cos.ap-beijing.myqcloud.com/b04e28cad0ee39193921a30a2eb4dc00/output/ComfyUI_00001_plhjr_1768892915.png",
      "nodeId": "2",
      "outputType": "png",
      "text": null
    }
  ],
  "clientId": "",
  "promptTips": ""
}
```

#### 响应字段说明

| 参数说明                   | 类型   | AI 应用程序生成的结果。                                      |
| -------------------------- | ------ | ------------------------------------------------------------ |
| `taskId`                   | String | 任务 ID                                                      |
| `status`                   | String | 任务最终状态，SUCCESS 表示生成成功                           |
| `results`                  | List   | 生成结果列表，包含图片、视频或文本等输出                     |
| ├ `url`                    | String | 重要提醒：该链接有效期仅为 24 小时。任务生成结束后，请务必在此时间窗口内将视频文件下载或转存至您的服务器。逾期后链接将永久失效且无法恢复。 |
| ├ `nodeId`                 | String | 生成该结果的工作流节点 ID                                    |
| ├ `outputType`             | String | 文件扩展名 (如 png, mp4, txt)                                |
| └ `text`                   | String | 如果输出是纯文本，内容将显示在此字段                         |
| `errorCode`                | String | 错误码 (如有)                                                |
| `errorMessage`             | String | 错误信息 (如有)                                              |
| `failedReason`             | Object | ComfyUI 相关的失败原因                                       |
| `usage`                    | Object | 任务消耗信息                                                 |
| ├ `thirdPartyConsumeMoney` | String | 三方API消费金额                                              |
| ├ `consumeMoney`           | String | 运行时长消耗金额                                             |
| ├ `consumeCoins`           | String | 运行消耗的RH币                                               |
| └ `taskCostTime`           | String | 运行耗时（ComfyUI 工作流运行时长）                           |
### 文件上传

资源文件（如 imageUrls）参数支持传入文件 URL 或 Base64 Data URI。

#### 公共 URL

直接传递可公开访问的 URL：

```json
{
  "imageUrls": [
    "https://example.com/image.png"
  ]
}
```

#### Base64 data URI

以 Base64 格式嵌入图片：

```json
{
  "images": [
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA..."
  ]
}
```

#### RH 上传接口

上传本地文件以获取一个 URL。

**Endpoint:** `https://www.runninghub.cn/openapi/v2/media/upload/binary`

**请求**

```curl
curl --location --request POST 'https://www.runninghub.cn/openapi/v2/media/upload/binary' \
--header 'Authorization: Bearer [Your API KEY]' \
--form 'file=@/path/to/image.png'
```

**响应**

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "type": "image",
    "download_url": "xxxx.png",
    "fileName": "openapi/xxxx.png",
    "size": "3490"
  }
}
```

**备注:** 上传后获得的链接有效期为 1 天，超期将无法通过 URL 直接访问。