# Code to accompany the paper "Constructions in combinatorics via neural networks and LP solvers" by A Z Wagner
# Code template
#
# This code works on tensorflow version 1.14.0 and python version 3.6.3
#
# For later versions of tensorflow there seems to be a massive overhead in the predict function for some reason, and/or it produces mysterious errors.
# If the code doesn't work, make sure you are using these versions of tf and python.
#
# I used keras version 2.3.1, not sure if this is important, but I recommend this just to be safe.

#Use this file as a template if you are able to use numba njit() for the calc_score function in your problem.
#Otherwise, if this is not an option, modify the simpler code in the *demos* folder

import numpy as np
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense
from tensorflow.keras.optimizers import Nadam
from discrepancy import calc_prefix_disc_simple
from dynamic import calc_prefix_disc_dp_count
import time
from numba import njit
from joblib import Parallel, delayed
import math

for i in range(100):

	N = 7 # number of elements
	M = 7 # number of sets
	DECISIONS = int(N*M)  # length of the word we are generating => adjency matrix stetched into one vector
	LEARNING_RATE = 0.0001 #Increase this to make convergence faster, decrease if the algorithm gets stuck in local optima too often.
	n_sessions = 1000 #number of new sessions per iteration
	percentile = 93 #top 100-X percentile we are learning from
	super_percentile = 94 #top 100-X percentile that survives to next iteration

	FIRST_LAYER_NEURONS = 512 #Number of neurons in the hidden layers.
	SECOND_LAYER_NEURONS = 256
	THIRD_LAYER_NEURONS = 16

	n_actions = 2 #The size of the alphabet. In this file we will assume this is 2. There are a few things we need to change when the alphabet size is larger,
				#such as one-hot encoding the input, and using categorical_crossentropy as a loss function.
				
	observation_space = 2*DECISIONS #Leave this at 2*DECISIONS. The input vector will have size 2*DECISIONS, where the first DECISIONS letters encode our partial word (with zeros on
							#the positions we haven't considered yet), and the next DECISIONS bits one-hot encode which letter we are considering now.
							#So e.g. [0,1,0,0,   0,0,1,0] means we have the partial word 01 and we are considering the third letter now.
							#Is there a better way to format the input to make it easier for the neural network to understand things?


							
	len_game = DECISIONS
	state_dim = (observation_space,)

	INF = 1000000

	#Model structure: a sequential network with three hidden layers, sigmoid activation in the output.
	#I usually used relu activation in the hidden layers but play around to see what activation function and what optimizer works best.
	#It is important that the loss is binary cross-entropy if alphabet size is 2.

	model = Sequential()
	model.add(Dense(FIRST_LAYER_NEURONS,  activation="relu"))
	model.add(Dense(SECOND_LAYER_NEURONS, activation="relu"))
	model.add(Dense(THIRD_LAYER_NEURONS, activation="relu"))
	model.add(Dense(1, activation="sigmoid"))
	model.build((None, observation_space))
	model.compile(loss="binary_crossentropy", optimizer=Nadam()) #Adam optimizer also works well, with lower learning rate


	print(model.summary())



	def calc_score(states,i):
		"""
		Reward function for your problem.

		Input: a 0-1 vector of length DECISIONS. It represents the graph (or other object) you have created.

		Output: the reward/score for your construction. See files in the *demos* folder for examples.	
		"""
		state = states[i]
		first_construction = state[0:DECISIONS]
		incidence = np.reshape(first_construction, (M, N))
		prefix_disc, count = calc_prefix_disc_simple(incidence)
		# prefix_disc, count = calc_prefix_disc_dp_count(incidence)

		return prefix_disc - (0.0001*math.log(count+1))

	####No need to change anything below here. 

	jitted_calc_score = njit()(calc_score)


	def play_game(actions, state_next, states, prob, step, total_score):
			
		for i in range(n_sessions):
		
			if np.random.rand() < prob[i]:
				action = 1
			else:
				action = 0
			actions[i][step-1] = action
			state_next[i] = states[i,:,step-1]

			if (action > 0):
				state_next[i][step-1] = action
			state_next[i][DECISIONS + step-1] = 0
			if (step < DECISIONS):
				state_next[i][DECISIONS + step] = 1			
			#calculate final score
			terminal = step == DECISIONS

			# record sessions 
			if not terminal:
				states[i,:,step] = state_next[i]
			
		return actions, state_next, states, terminal

	jitted_play_game = njit()(play_game)

	def generate_session(agent, n_sessions, verbose = 1):
		"""
		Play n_session games using agent neural network.
		Terminate when games finish 
		
		Code inspired by https://github.com/yandexdataschool/Practical_RL/blob/master/week01_intro/deep_crossentropy_method.ipynb
		"""
		states =  np.zeros([n_sessions, observation_space, len_game], dtype=np.int8)
		actions = np.zeros([n_sessions, len_game], dtype=np.int8)
		state_next = np.zeros([n_sessions,observation_space], dtype=np.int8)
		prob = np.zeros(n_sessions)
		states[:,DECISIONS,0] = 1
		step = 0
		total_score = np.zeros([n_sessions])
		pred_time = 0
		play_time = 0
		
		while (True):
			step += 1		
			tic = time.time()
			prob = agent.predict(states[:,:,step-1], verbose=0) # batch_size=n_sessions
			# prob = predict_joblib(states, step, agent, 4) # distributed version
			pred_time += time.time()-tic
			tic = time.time()
			actions, state_next, states, terminal = jitted_play_game(actions,state_next,states,prob, step, total_score)
			play_time += time.time()-tic
			
			if terminal:
				tic = time.time()
				total_score = Parallel(n_jobs=-1)(delayed(jitted_calc_score)(state_next,i) for i in range(n_sessions))
				play_time += time.time()-tic
				break
		if (verbose):
			print("Predict: "+str(pred_time)+", play: " + str(play_time))
		return states, actions, total_score
		

	def select_elites(states_batch, actions_batch, rewards_batch, percentile=50):
		"""
		Select states and actions from games that have rewards >= percentile
		:param states_batch: list of lists of states, states_batch[session_i][t]
		:param actions_batch: list of lists of actions, actions_batch[session_i][t]
		:param rewards_batch: list of rewards, rewards_batch[session_i]

		:returns: elite_states,elite_actions, both 1D lists of states and respective actions from elite sessions
		
		This function was mostly taken from https://github.com/yandexdataschool/Practical_RL/blob/master/week01_intro/deep_crossentropy_method.ipynb
		If this function is the bottleneck, it can easily be sped up using numba
		"""
		counter = n_sessions * (100.0 - percentile) / 100.0
		reward_threshold = np.percentile(rewards_batch,percentile)

		elite_states = []
		elite_actions = []
		elite_rewards = []
		for i in range(len(states_batch)):
			if rewards_batch[i] >= reward_threshold-0.0000001:		
				if (counter > 0) or (rewards_batch[i] >= reward_threshold+0.0000001):
					for item in states_batch[i]:
						elite_states.append(item.tolist())
					for item in actions_batch[i]:
						elite_actions.append(item)			
				counter -= 1
		elite_states = np.array(elite_states, dtype=np.int8)	
		elite_actions = np.array(elite_actions, dtype=np.int8)	
		return elite_states, elite_actions
		
	def select_super_sessions(states_batch, actions_batch, rewards_batch, percentile=90):
		"""
		Select all the sessions that will survive to the next generation
		Similar to select_elites function
		If this function is the bottleneck, it can easily be sped up using numba
		"""
		
		counter = n_sessions * (100.0 - percentile) / 100.0
		reward_threshold = np.percentile(rewards_batch,percentile)

		super_states = []
		super_actions = []
		super_rewards = []
		for i in range(len(states_batch)):
			if rewards_batch[i] >= reward_threshold-0.0000001:
				if (counter > 0) or (rewards_batch[i] >= reward_threshold+0.0000001):
					super_states.append(states_batch[i])
					super_actions.append(actions_batch[i])
					super_rewards.append(rewards_batch[i])
					counter -= 1
		super_states = np.array(super_states, dtype=np.int8)
		super_actions = np.array(super_actions, dtype=np.int8)
		super_rewards = np.array(super_rewards)
		return super_states, super_actions, super_rewards
		

	super_states =  np.empty((0,len_game,observation_space), dtype=np.int8)
	super_actions = np.array([], dtype=np.int8)
	super_rewards = np.array([])
	sessgen_time = 0
	fit_time = 0
	score_time = 0


	######################################################################
	# 								 ADDED						    	 #
	######################################################################

	found_first = False
	found_100 = False
	counter = 0
	counter_first = -10
	count_100 = -10

	while(found_100 == False):

		#generate new sessions
		#performance can be improved with joblib
		tic = time.time()
		sessions = generate_session(model,n_sessions,1) #change 0 to 1 to print out how much time each step in generate_session takes 
		sessgen_time = time.time()-tic
		tic = time.time()
		
		states_batch = np.array(sessions[0], dtype=np.int8)
		actions_batch = np.array(sessions[1], dtype=np.int8)
		rewards_batch = np.array(sessions[2])
		states_batch = np.transpose(states_batch,axes=[0,2,1])
		
		states_batch = np.append(states_batch,super_states,axis=0)

		if counter>0:
			actions_batch = np.append(actions_batch,np.array(super_actions),axis=0)	
		rewards_batch = np.append(rewards_batch,super_rewards)
			
		randomcomp_time = time.time()-tic 
		tic = time.time()

		elite_states, elite_actions = select_elites(states_batch, actions_batch, rewards_batch, percentile=percentile) #pick the sessions to learn from
		select1_time = time.time()-tic

		tic = time.time()
		super_sessions = select_super_sessions(states_batch, actions_batch, rewards_batch, percentile=super_percentile) #pick the sessions to survive
		select2_time = time.time()-tic
		
		tic = time.time()
		super_sessions = [(super_sessions[0][i], super_sessions[1][i], super_sessions[2][i]) for i in range(len(super_sessions[2]))]
		super_sessions.sort(key=lambda super_sessions: super_sessions[2],reverse=True)
		select3_time = time.time()-tic
		
		tic = time.time()
		model.fit(elite_states, elite_actions, verbose=0) #learn from the elite sessions
		fit_time = time.time()-tic
		
		tic = time.time()
		
		super_states = [super_sessions[i][0] for i in range(len(super_sessions))]
		super_actions = [super_sessions[i][1] for i in range(len(super_sessions))]
		super_rewards = [super_sessions[i][2] for i in range(len(super_sessions))]
		
		rewards_batch.sort()
		mean_all_reward = np.mean(rewards_batch[-100:])	
		mean_best_reward = np.mean(super_rewards)	

		score_time = time.time()-tic
		
		print("\n" + str(counter) +  ". Best individuals: " + str(np.flip(np.sort(super_rewards))))
		
		#uncomment below line to print out how much time each step in this loop takes. 
		print(	"Mean reward: " + str(mean_all_reward) + "\nSessgen: " + str(sessgen_time) + ", other: " + str(randomcomp_time) + ", select1: " + str(select1_time) + ", select2: " + str(select2_time) + ", select3: " + str(select3_time) +  ", fit: " + str(fit_time) + ", score: " + str(score_time)) 
		

		######################################################################
		# 								 ADDED						    	 #
		######################################################################
		
		counter += 1

		if (super_rewards[0] > 2) and (found_first == False):
			counter_first = counter
			found_first = True

		if mean_all_reward > 2.98:
			counter_100 = counter
			found_100 = True
		
	with open('search_count_first.txt', 'a') as f:
		f.write(str(counter_first)+"\n")
	with open('search_count_100.txt', 'a') as f:
		f.write(str(counter_100)+"\n")