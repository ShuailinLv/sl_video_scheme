import time
import numpy as np
import pythoncom
import soundcard as sc


def main():
    pythoncom.CoInitialize()
    try:
        mics = list(sc.all_microphones(include_loopback=False))
        print("available microphones:")
        for i, mic in enumerate(mics):
            print(f"  [{i}] {mic.name!r}")

        mic = mics[0]
        print(f"\\nusing: {mic.name!r}")

        with mic.recorder(samplerate=48000, channels=1) as rec:
            print("start recording... speak now")
            for i in range(20):
                data = rec.record(numframes=1024)
                audio = np.asarray(data, dtype=np.float32).reshape(-1)
                rms = float(np.sqrt(np.mean(np.square(audio)))) if audio.size else 0.0
                peak = float(np.max(np.abs(audio))) if audio.size else 0.0
                print(f"[{i:02d}] shape={audio.shape} rms={rms:.6f} peak={peak:.6f}")
                time.sleep(0.1)
    finally:
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    main()