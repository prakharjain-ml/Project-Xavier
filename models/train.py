import pandas as pd
import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer

df = pd.read_csv("clench_emg_features.csv")

# Use only the numerical muscle-signal features.
features = [c for c in df.columns
            if c.startswith(("ch1_", "ch2_"))]

# Hold out entire trials, not randomly selected windows.
test_trials = {"clench_5", "clench_6", "relax_5", "relax_6"}
test_mask = df["trial_id"].isin(test_trials)

train = df[~test_mask]
test = df[test_mask]

X_train = train[features]
y_train = train["label"]

X_test = test[features]
y_test = test["label"]

model = make_pipeline(
    SimpleImputer(strategy="median"),
    RandomForestClassifier(
        n_estimators=100,
        max_depth=4,
        class_weight="balanced",
        random_state=42
    )
)

model.fit(X_train, y_train)

predictions = model.predict(X_test)

print("Training windows:", len(train))
print("Testing windows:", len(test))
print("\nConfusion matrix:")
print(confusion_matrix(y_test, predictions, labels=[0, 1]))
print("\nClassification report:")
print(classification_report(
    y_test, predictions,
    labels=[0, 1],
    target_names=["Relax", "Clench"],
    zero_division=0
))

joblib.dump(
    {"model": model, "features": features},
    "clench_model.joblib"
)

print("\nSaved clench_model.joblib")
