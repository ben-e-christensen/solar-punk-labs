// endstop dimensions

$fn=100;

e_x=35;
e_y=11;
u_left=11.3;
u_right=17.7;
bh=28;
in=25.4;

m3=3.2/2;

z=3;


shift=e_x/2-z/2-u_right;
shift1=-e_x/2+z/2+u_left;
module stop(height=in){
difference(){
    union(){
        cube([e_x,e_y*2.5,z],center=true);
        translate([shift,0,height/2+z/2])
        cube([z-.5,e_y*2.5,height],center=true);
//        translate([shift1,e_y,height/2+z/2])
//        cube([z,e_y,height],center=true);
    }
    
    translate([bh/2,0,-3])
    cylinder(100,m3,m3);
    translate([-bh/2,0,-3])
    cylinder(100,m3,m3);
}
}

module bracket(){
    difference(){
        cube([e_x+6,e_y,120],center=true);
        cube([e_x,e_y+3,120-6],center=true);
        translate([bh/2,0,-75])
        cylinder(150,m3,m3);
        translate([-bh/2,0,-75])
        cylinder(150,m3,m3);
    }
}
stop();
    


