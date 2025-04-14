from flask import Flask, render_template, request, redirect, session, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from model import db, User, Service, Order, Review, Complaint, ContactMessage
from forms import RegisterForm, LoginForm,ReviewForm
from flask_wtf.csrf import CSRFProtect

import os
from werkzeug.utils import secure_filename
from sqlalchemy import func

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
app.config['SECRET_KEY'] = 'your-secret-key'
app.config['WTF_CSRF_ENABLED'] = True

csrf = CSRFProtect(app)
db.init_app(app)
migrate = Migrate(app, db)

# Create database tables
with app.app_context():
    db.create_all()

UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Create uploads directory if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def home():
    # Get services with their review counts and average ratings
    service_reviews = db.session.query(
        Service.id,
        func.count(Review.id).label('review_count'),
        func.avg(Review.rating).label('avg_rating')
    ).outerjoin(Review, Service.id == Review.service_id)\
     .group_by(Service.id).subquery()

    # Calculate a score for each service
    # Score = (average rating * number of reviews) / (price / 1000)
    # This gives higher scores to services with good ratings, many reviews, and reasonable prices
    top_services = db.session.query(Service).\
        outerjoin(service_reviews, Service.id == service_reviews.c.id).\
        order_by(
            (service_reviews.c.avg_rating * service_reviews.c.review_count * 1000.0 / Service.price).desc()
        ).\
        limit(3).all()
    
    return render_template('home.html', services=top_services)

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/services')
def services():
    # Get filter parameters
    category = request.args.get('category', '')
    price_range = request.args.get('price_range', '')
    
    # Start with all services
    query = Service.query
    
    # Apply category filter if selected
    if category:
        query = query.filter(Service.category == category)
    
    # Apply price range filter if selected
    if price_range:
        price_min, price_max = map(int, price_range.split('-'))
        query = query.filter(Service.price >= price_min, Service.price <= price_max)
    
    # Get filtered services
    services = query.all()
    
    return render_template('services.html', services=services)

@app.route('/contact', methods=['POST'])
def contact():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        message = request.form['message']
        
        # Save message to database
        new_message = ContactMessage(
            name=name,
            email=email,
            message=message
        )
        
        try:
            db.session.add(new_message)
            db.session.commit()
            flash('Thank you for your message! We will get back to you soon.', 'success')
        except:
            db.session.rollback()
            flash('An error occurred while sending your message. Please try again.', 'error')
        
        return redirect(url_for('about'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        try:
            # Check if email already exists
            existing_user = User.query.filter_by(email=form.email.data).first()
            if existing_user:
                flash('Email already registered. Please use a different email or login.', 'error')
                return render_template('register.html', form=form)
            
            user = User(
                role=form.role.data,
                name=form.name.data,
                email=form.email.data,
                mobile=form.mobile.data,
                password=form.password.data
            )
            db.session.add(user)
            db.session.commit()
            flash('Registration successful! Please login to continue.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            db.session.rollback()
            flash('An error occurred during registration. Please try again.', 'error')
            return render_template('register.html', form=form)
    
    return render_template('register.html', form=form)


@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        try:
            email = form.email.data
            password = form.password.data
            
            # Check for admin login
            if email == 'admin' and password == 'admin':
                session['role'] = 'admin'
                flash('Admin login successful!', 'success')
                return redirect(url_for('admin_panel'))
            
            user = User.query.filter_by(email=email, password=password).first()
            
            if user:
                session['user_id'] = user.id
                session['role'] = user.role
                flash('Login successful!', 'success')
                if user.role == 'organizer':
                    return redirect(url_for('profile_organizer'))
                else:
                    return redirect(url_for('profile_customer'))
            else:
                flash('Invalid email or password. Please try again.', 'error')
        except Exception as e:
            flash('An error occurred during login. Please try again.', 'error')
    
    return render_template('login.html', form=form)


@app.route('/add_service', methods=['GET', 'POST'])
def add_service():
    if 'user_id' not in session or session['role'] != 'organizer':
        return redirect(url_for('login'))

    if request.method == 'POST':
        title = request.form['title']
        category = request.form['category']
        description = request.form['description']
        price = int(request.form['price'])
        image = request.files['image']

        # Validate price
        if price < 0 or price % 500 != 0:
            flash('Price must be a positive multiple of 500', 'error')
            return redirect(url_for('add_service'))

        image_filename = None
        if image and allowed_file(image.filename):
            filename = secure_filename(image.filename)
            image_filename = filename
            image.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        new_service = Service(
            title=title,
            category=category,
            description=description,
            price=price,
            image=image_filename,
            organizer_id=session['user_id']
        )
        db.session.add(new_service)
        db.session.commit()
        flash('Service added successfully!', 'success')
        return redirect(url_for('profile_organizer'))

    return render_template('add_service.html')

@app.route('/service/<int:service_id>/review', methods=['GET', 'POST'])
def review(service_id):
    if 'user_id' not in session or session['role'] != 'customer':
        return redirect(url_for('login'))

    service = Service.query.get_or_404(service_id)
    form = ReviewForm()

    if form.validate_on_submit():
        review = Review(
            service_id=service.id,
            customer_id=session['user_id'],
            rating=int(form.rating.data),
            comment=form.comment.data
        )
        db.session.add(review)
        db.session.commit()
        return redirect(url_for('services'))

    reviews = Review.query.filter_by(service_id=service_id).all()
    return render_template('review_form.html', form=form, service=service, reviews=reviews)

@app.route('/place_order/<int:service_id>', methods=['POST'])
def place_order(service_id):
    if 'user_id' not in session or session['role'] != 'customer':
        return redirect(url_for('login'))
    
    # Get the service information
    service = Service.query.get_or_404(service_id)
    
    # Create the new order
    new_order = Order(service_id=service_id, customer_id=session['user_id'], status='Pending')
    db.session.add(new_order)
    db.session.commit()
    
    # Flash a success message
    flash(f'Your order for "{service.title}" has been placed successfully!', 'success')
    return redirect(url_for('profile_customer'))


@app.route('/profile/customer')
def profile_customer():
    if 'user_id' not in session or session['role'] != 'customer':
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    orders = Order.query.filter_by(customer_id=user.id).all()
    return render_template('profile_customer.html', user=user, orders=orders)

@app.route('/profile/organizer')
def profile_organizer():
    if 'user_id' not in session or session['role'] != 'organizer':
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])

    services = Service.query.filter_by(organizer_id=user.id).all()
    service_ids = [s.id for s in services]
    orders = Order.query.filter(Order.service_id.in_(service_ids)).all()

    return render_template('profile_organizer.html', user=user, services=services, orders=orders)

@app.route('/update_order_status/<int:order_id>', methods=['POST'])
def update_order_status(order_id):
    if 'user_id' not in session or session['role'] != 'organizer':
        return redirect(url_for('login'))
    
    order = Order.query.get_or_404(order_id)
    service = Service.query.get(order.service_id)
    
    # Verify this order belongs to one of the organizer's services
    if service.organizer_id != session['user_id']:
        flash('You do not have permission to update this order', 'error')
        return redirect(url_for('profile_organizer'))
    
    new_status = request.form.get('status')
    if new_status in ['Pending', 'Confirmed', 'Completed', 'Cancelled']:
        order.status = new_status
        db.session.commit()
        flash(f'Order status updated to {new_status}', 'success')
    
    return redirect(url_for('profile_organizer'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/submit_complaint', methods=['POST'])
def submit_complaint():
    if request.method == 'POST':
        if 'user_id' not in session:
            flash('Please login to submit a complaint', 'error')
            return redirect(url_for('login'))
            
        complaint_type = request.form['complaint_type']
        complaint_details = request.form['complaint_details']
        attachment = request.files.get('complaint_attachment')
        
        # Handle file upload if present
        attachment_filename = None
        if attachment and allowed_file(attachment.filename):
            filename = secure_filename(attachment.filename)
            attachment_filename = filename
            attachment.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        
        # Create new complaint
        new_complaint = Complaint(
            user_id=session['user_id'],
            complaint_type=complaint_type,
            details=complaint_details,
            attachment=attachment_filename
        )
        
        db.session.add(new_complaint)
        db.session.commit()
        
        flash('Thank you for your feedback. We will review your complaint and get back to you.', 'success')
        return redirect(url_for('about'))

@app.route('/edit_service/<int:service_id>', methods=['GET', 'POST'])
def edit_service(service_id):
    if 'user_id' not in session or session['role'] != 'organizer':
        return redirect(url_for('login'))
    
    service = Service.query.get_or_404(service_id)
    
    # Check if the service belongs to the logged-in organizer
    if service.organizer_id != session['user_id']:
        flash('You do not have permission to edit this service', 'error')
        return redirect(url_for('profile_organizer'))
    
    if request.method == 'POST':
        service.title = request.form['title']
        service.category = request.form['category']
        service.description = request.form['description']
        service.price = int(request.form['price'])
        
        image = request.files.get('image')
        if image and allowed_file(image.filename):
            filename = secure_filename(image.filename)
            image.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            service.image = filename
        
        try:
            db.session.commit()
            flash('Service updated successfully!', 'success')
            return redirect(url_for('profile_organizer'))
        except:
            db.session.rollback()
            flash('An error occurred while updating the service', 'error')
    
    return render_template('edit_service.html', service=service)

@app.route('/delete_service/<int:service_id>', methods=['POST'])
def delete_service(service_id):
    if 'user_id' not in session or session['role'] != 'organizer':
        return redirect(url_for('login'))
    
    service = Service.query.get_or_404(service_id)
    
    # Check if the service belongs to the logged-in organizer
    if service.organizer_id != session['user_id']:
        flash('You do not have permission to delete this service', 'error')
        return redirect(url_for('profile_organizer'))
    
    try:
        # Delete the service image if it exists
        if service.image:
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], service.image)
            if os.path.exists(image_path):
                os.remove(image_path)
        
        # Delete the service
        db.session.delete(service)
        db.session.commit()
        flash('Service deleted successfully!', 'success')
    except:
        db.session.rollback()
        flash('An error occurred while deleting the service', 'error')
    
    return redirect(url_for('profile_organizer'))

# Admin Panel Routes
@app.route('/admin')
def admin_panel():
    users = User.query.all()
    services = Service.query.all()
    orders = Order.query.all()
    complaints = Complaint.query.all()
    messages = ContactMessage.query.all()
    
    return render_template('admin_panel.html', 
                         users=users,
                         services=services,
                         orders=orders,
                         complaints=complaints,
                         messages=messages)

@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    try:
        db.session.delete(user)
        db.session.commit()
        flash('User deleted successfully!', 'success')
    except:
        db.session.rollback()
        flash('An error occurred while deleting the user', 'error')
    
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete_service/<int:service_id>', methods=['POST'])
def admin_delete_service(service_id):
    service = Service.query.get_or_404(service_id)
    try:
        # Delete the service image if it exists
        if service.image:
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], service.image)
            if os.path.exists(image_path):
                os.remove(image_path)
        
        db.session.delete(service)
        db.session.commit()
        flash('Service deleted successfully!', 'success')
    except:
        db.session.rollback()
        flash('An error occurred while deleting the service', 'error')
    
    return redirect(url_for('admin_panel'))

@app.route('/admin/view_complaint/<int:complaint_id>')
def view_complaint(complaint_id):
    complaint = Complaint.query.get_or_404(complaint_id)
    return render_template('view_complaint.html', complaint=complaint)

@app.route('/admin/update_complaint_status/<int:complaint_id>', methods=['POST'])
def update_complaint_status(complaint_id):
    complaint = Complaint.query.get_or_404(complaint_id)
    new_status = request.form.get('status')
    
    if new_status in ['Pending', 'In Progress', 'Resolved', 'Closed']:
        complaint.status = new_status
        try:
            db.session.commit()
            flash('Complaint status updated successfully!', 'success')
        except:
            db.session.rollback()
            flash('An error occurred while updating the complaint status', 'error')
    
    return redirect(url_for('admin_panel'))

@app.route('/admin/view_message/<int:message_id>')
def view_message(message_id):
    message = ContactMessage.query.get_or_404(message_id)
    return render_template('view_message.html', message=message)

@app.route('/admin/delete_message/<int:message_id>', methods=['POST'])
def delete_message(message_id):
    message = ContactMessage.query.get_or_404(message_id)
    try:
        db.session.delete(message)
        db.session.commit()
        flash('Message deleted successfully!', 'success')
    except:
        db.session.rollback()
        flash('An error occurred while deleting the message', 'error')
    
    return redirect(url_for('admin_panel'))

if __name__ == '__main__':
    app.run(debug=True)
