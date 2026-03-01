---
library_name: transformers
pipeline_tag: image-segmentation
tags:
  - image-segmentation
  - mask-generation
  - transformers.js
  - vision
  - background-removal
  - portrait-matting
license: apache-2.0
language:
  - en
---
# U-2-Net

## Model Description
U-2-Net is a deep learning model designed for image segmentation tasks, particularly for generating detailed masks. It leverages a unique architecture with nested U-blocks that allow the model to capture both high-level semantic features and fine-grained details. U-2-Net has demonstrated high performance in a variety of segmentation tasks, making it a versatile choice for applications such as background removal, object detection, and medical image analysis.

## Usage
Perform mask generation with `BritishWerewolf/U-2-Net`.

### Example
```javascript
import { AutoModel, AutoProcessor, RawImage } from '@huggingface/transformers';

const img_url = 'https://huggingface.co/ybelkada/segment-anything/resolve/main/assets/car.png';
const image = await RawImage.read(img_url);

const processor = await AutoProcessor.from_pretrained('BritishWerewolf/U-2-Net');
const processed = await processor(image);

const model = await AutoModel.from_pretrained('BritishWerewolf/U-2-Net', {
    dtype: 'fp32',
});

const output = await model({ input: processed.pixel_values });
// {
//   mask: Tensor {
//     dims: [ 1, 320, 320 ],
//     type: 'uint8',
//     data: Uint8Array(102400) [ ... ],
//     size: 102400
//   }
// }
```

## Model Architecture
The U-2-Net model is built upon a nested U-structure, where each U-block consists of multiple convolutional layers, pooling, and up-sampling operations. The architecture features a combination of down-sampling and up-sampling paths, enabling the model to learn features at different scales. This design allows the U-2-Net to produce accurate and high-resolution segmentation maps. The key components of the architecture include Residual U-blocks (RSU) that enhance feature representation and ensure efficient information flow through the network.

### Inference
To use the model for inference, you can follow the example provided above. The `AutoProcessor` and `AutoModel` classes from the `transformers` library make it easy to load the model and processor.

## Credits
* [`rembg`](https://github.com/danielgatis/rembg) for the ONNX model.
* The authors of the original U-2-Net model can be credited at https://github.com/xuebinqin/U-2-Net.

## Licence
This model is licensed under the Apache License 2.0 to match the original U-2-Net model.
