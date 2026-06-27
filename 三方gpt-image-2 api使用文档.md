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