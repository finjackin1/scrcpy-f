package android.graphics;

import java.io.OutputStream;

public final class Bitmap {
    public enum Config { ALPHA_8, RGB_565, ARGB_4444, ARGB_8888 }
    public enum CompressFormat { JPEG, PNG, WEBP }
    public int getWidth() { return 0; }
    public int getHeight() { return 0; }
    public int getPixel(int x, int y) { return 0; }
    public Bitmap copy(Config c, boolean mutavel) { return null; }
    public boolean compress(CompressFormat f, int q, OutputStream o) { return false; }
    public static Bitmap createScaledBitmap(Bitmap b, int w, int h, boolean f) { return null; }
    public static Bitmap createBitmap(int w, int h, Config c) { return null; }
}