package android.app;

import android.content.Intent;
import android.os.Bundle;

public final class RemoteInput {
    public String getResultKey() { return null; }
    public boolean getAllowFreeFormInput() { return false; }
    public CharSequence getLabel() { return null; }
    public static void addResultsToIntent(RemoteInput[] r, Intent i, Bundle b) {}
    public static void setResultsSource(Intent i, int source) {}
}