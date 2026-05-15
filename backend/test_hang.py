import os
from app.pipeline import EsnafKopilotPipeline

def test():
    print("Testing pipeline...")
    pipe = EsnafKopilotPipeline()
    result = pipe.run("https://www.trendyol.com/tala/hindistan-cevizi-yagi-100-saf-ve-dogal-soguk-sikim-150-ml-p-322236564", 1)
    print("Finished:", result)

if __name__ == "__main__":
    test()
