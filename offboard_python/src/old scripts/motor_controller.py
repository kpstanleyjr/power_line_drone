#!/usr/bin/env python

import rospy
import mavros
import sys
from math import sin, cos, fabs
from geometry_msgs.msg import PoseStamped, Twist
from mavros_msgs.msg import State 
from mavros_msgs.srv import CommandBool, SetMode
from std_msgs.msg import Float64, String
from tf.transformations import *
from sensor_msgs.msg import LaserScan

# callback method for state sub
current_state = State() 
offb_set_mode = SetMode
def state_cb(state):
    global current_state
    current_state = state

#callback method for rplidar subscriber
def rplidar_cb(data):
    """ Unnecessary information 
    global angle_min
    angle_min = data.angle_min
    global angle_max
    angle_max = data.angle_max
    global angle_increment
    angle_increment = data.angle_increment
    global time_increment
    time_increment = data.time_increment
    global scan_time
    scan_time = data.scan_time
    """
    global range_min
    range_min = data.range_min
    global range_max
    range_max = data.range_max
    global ranges
    ranges = data.ranges
    global intensities
    intensities = data.intensities

#callback method for state_machine subscriber
def state_machine_cb(state):
    global state_machine
    state_machine = state.data


#callback method for position subscriber
def position_cb(get_pose):
    global altitude
    altitude = get_pose.pose.position.z
    global x_position
    x_position = get_pose.pose.position.x
    global y_position
    y_position = get_pose.pose.position.y


mavros.set_namespace()
local_pos_pub = rospy.Publisher(mavros.get_topic('setpoint_position', 'local'), PoseStamped, queue_size=10)
body_vel_pub = rospy.Publisher(mavros.get_topic('setpoint_velocity', 'cmd_vel_unstamped'), Twist, queue_size=10)

state_sub = rospy.Subscriber(mavros.get_topic('state'), State, state_cb)
laser_sub = rospy.Subscriber('scan', LaserScan, rplidar_cb)
state_machine_sub = rospy.Subscriber('state_machine', String, state_machine_cb)
local_pos_sub = rospy.Subscriber(mavros.get_topic('local_position', 'pose'), PoseStamped, position_cb)

arming_client = rospy.ServiceProxy(mavros.get_topic('cmd', 'arming'), CommandBool)
set_mode_client = rospy.ServiceProxy(mavros.get_topic('set_mode'), SetMode) 

targetHeight = 2
pose = PoseStamped()
pose.pose.position.x = 0
pose.pose.position.y = 0
pose.pose.position.z = targetHeight

x_accum_error = 0 
y_accum_error = 0 
Kp = 1
Ki = 0.01

danger_zone = 0.3

def position_control():
    freq = 20.0
    rospy.init_node('motor_controller', anonymous=True)
    prev_state = current_state
    rate = rospy.Rate(freq) # MUST be more then 2Hz

    # send a few setpoints before starting
    for i in range(100):
        local_pos_pub.publish(pose)
        rate.sleep()
    

    count = 0
    # wait for FCU connection
    while not current_state.connected:
        rate.sleep()

    last_request = rospy.get_rostime()
    while not rospy.is_shutdown():
	count = count + 0.05
        now = rospy.get_rostime()
        if current_state.mode != "OFFBOARD" and (now - last_request > rospy.Duration(5.)):
            set_mode_client(base_mode=0, custom_mode="OFFBOARD")
            last_request = now 
        else:
            if not current_state.armed and (now - last_request > rospy.Duration(5.)):
               arming_client(True)
               last_request = now 

        # older versions of PX4 always return success==True, so better to check Status instead
        if prev_state.armed != current_state.armed:
            rospy.loginfo("Vehicle armed: %r" % current_state.armed)
        if prev_state.mode != current_state.mode: 
            rospy.loginfo("Current mode: %s" % current_state.mode)
            offboard_started_time = rospy.get_rostime()
        prev_state = current_state

        # Update timestamp and publish pose
	now = rospy.get_rostime()
	if (current_state.mode == "OFFBOARD" and now - offboard_started_time <= rospy.Duration(10.)):
            pose.header.stamp = rospy.Time.now()
            local_pos_pub.publish(pose)
            rate.sleep()
	else:
	    #create and send velocity setpoints
	    twist = Twist()
	    """
	    VARIABLES
	    twist.linear.x = xvel
	    twist.linear.y = yvel
	    twist.linear.z = zvel
	    twist.angular.x = pitch
	    twist.angular.y = roll
	    twist.angular.z = yaw
	    """

	    closest_obstacle = min(ranges)
	    obstacle_angle = ranges.index(closest_obstacle) 
	    obstacle_distance = ranges[obstacle_angle]

	    if closest_obstacle < danger_zone:
		x_direction = -math.cos(obstacle_angle*(math.pi/180))
		y_direction = -math.sin(obstacle_angle*(math.pi/180))

		x_velocity = x_direction * (danger_zone - obstacle_distance) * 8
		y_velocity = y_direction * (danger_zone - obstacle_distance) * 8

		sys.stdout.write("Avoiding Obstacle: %s \r" % (obstacle_angle) )
		sys.stdout.flush()

	    else:
		x_error = -x_position 
		y_error = -y_position

		x_accum_error += x_error * (1/freq) 
		y_accum_error += y_error * (1/freq)

		P_x = x_error*Kp 
		P_y = y_error*Kp

		I_x = x_accum_error*Ki 
		I_y = y_accum_error*Ki

		x_velocity = P_x #+ I_x 
		y_velocity = P_y #+ I_y

		print("\nx position: ")
		print(x_position)
		print("\ny position: ")
		print(y_position)		


		'''sys.stdout.write("Hovering\r")
		sys.stdout.flush()
		'''

	    if altitude < targetHeight:
		z_velocity = 0.2 
	    else:
		z_velocity = 0
	    

	        
	    twist.linear.x = x_velocity
	    twist.linear.y = y_velocity
	    twist.linear.z = z_velocity
	    twist.angular.x = 0
	    twist.angular.y = 0
	    twist.angular.z = 0  

	    body_vel_pub.publish(twist)

	    # print(ranges.index(min(ranges)))
  


if __name__ == '__main__':
    try:
        position_control()
    except rospy.ROSInterruptException:
	pass
