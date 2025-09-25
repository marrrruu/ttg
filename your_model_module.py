import tensorflow as tf
from tensorflow.keras.preprocessing import image
import numpy as np

def load_model(model_path):
    """Загрузка предварительно обученной модели"""
    return tf.keras.models.load_model(model_path)

def predict_image(model, image_path):
    """Классификация изображения"""
    img = image.load_img(image_path, target_size=(200, 200))
    x = image.img_to_array(img) / 255.
    x = np.expand_dims(x, axis=0)
    
    pred = model.predict(x)[0][0]
    confidence = max(pred, 1-pred)
    
    if pred < 0.5:
        return "Человек", 1-pred
    else:
        return "Обезьяна", pred