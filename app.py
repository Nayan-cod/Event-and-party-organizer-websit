from flask import Flask, render_template, request, redirect, session, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from model import db, User, Service, Order, Review
from forms import RegisterForm, LoginForm,ReviewForm

import os
from werkzeug.utils import secure_filename
from sqlalchemy import func

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
app.config['SECRET_KEY'] = 'your-secret-key'



db.init_app(app)


UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def home():
    # Get the most ordered services by counting orders for each service
    # Use a subquery to count orders for each service
    
    # Get count of orders for each service
    service_order_counts = db.session.query(
        Order.service_id, 
        func.count(Order.id).label('order_count')
    ).group_by(Order.service_id).subquery()
    
    # Join with services and order by count
    top_services = db.session.query(Service).\
        outerjoin(service_order_counts, Service.id == service_order_counts.c.service_id).\
        order_by(service_order_counts.c.order_count.desc().nullslast()).\
        limit(4).all()
    
    # If there are fewer than 4 ordered services, add others to make up the count
    if len(top_services) < 4:
        existing_ids = [s.id for s in top_services]
        additional_services = Service.query.filter(~Service.id.in_(existing_ids)).limit(4 - len(top_services)).all()
        top_services.extend(additional_services)
    
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

@app.route('/contact')
def contact():
    return render_template('contact.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        user = User(
            role=form.role.data,
            name=form.name.data,
            email=form.email.data,
            mobile=form.mobile.data,
            password=form.password.data
        )
        db.session.add(user)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('register.html', form=form)


@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data
        password = form.password.data
        user = User.query.filter_by(email=email, password=password).first()
        if user:
            session['user_id'] = user.id
            session['role'] = user.role
            if user.role == 'organizer':
                return redirect(url_for('profile_organizer'))
            else:
                return redirect(url_for('profile_customer'))
    return render_template('login.html', form=form)  # Pass 'form' to template


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

if __name__ == '__main__':
    app.run(debug=True)
