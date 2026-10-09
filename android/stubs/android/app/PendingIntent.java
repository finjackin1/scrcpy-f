package android.app;

import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;

public final class PendingIntent {
    public interface OnFinished {
        void onSendFinished(PendingIntent pi, Intent intent, int resultCode,
                            String resultData, Bundle resultExtras);
    }
    public static class CanceledException extends Exception {}
    public void send() throws CanceledException {}
    public void send(Context c, int code, Intent i, OnFinished f, Handler h,
                     String perm, Bundle options) throws CanceledException {}
    public boolean isActivity() { return false; }
}