I built a football match prediction pipeline using five seasons of Premier League data. 
The project focuses on preventing data leakage through chronological feature engineering and evaluation. 

Final model: Logistic Regression Test 
Season: 2025–26
Accuracy: 48.7% 
Log loss: 1.051 

###

If you predicted a home win for every game, you would have an accuracy of 42.6%
This model beats this with an increase of 6.1%.

### 

Key findings 

- Season-long points per game was the strongest predictor. 
- Defensive metrics were more informative than attacking metrics. 
- Venue-specific recent form did not improve performance. 
- The model struggled to predict draws, a common limitation of 3-class football prediction. 
- Predictions with probabilities above 0.55 achieved approximately 57% accuracy. 

### 

Techniques used 
- Rolling last-5 features 
- Season-to-date statistics 
- Chronological train/test split 
- Probability calibration analysis 
- Feature importance interpretation 
- Model comparison (Logistic Regression vs Random Forest)

###

To set it up:

python -m venv .venv 

source .venv/bin/activate # Linux/Mac 

or 

.venv\Scripts\activate # Windows 

pip install -r requirements.txt
