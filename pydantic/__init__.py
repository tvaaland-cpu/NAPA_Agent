from __future__ import annotations


class BaseModel:
    def __init__(self, **data):
        annotations = getattr(self.__class__, "__annotations__", {})
        for key in annotations:
            if key in data:
                value = data[key]
            elif hasattr(self.__class__, key):
                value = getattr(self.__class__, key)
            else:
                value = None
            setattr(self, key, value)

        for key, value in data.items():
            if key not in annotations:
                setattr(self, key, value)

    def model_dump(self):
        return dict(self.__dict__)
